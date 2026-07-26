//@category V8Bytecode

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.SourceType;

public class DumpV8Decompile extends GhidraScript {

	private static class EntryPoint {
		private final String kind;
		private final long offset;

		EntryPoint(String kind, long offset) {
			this.kind = kind;
			this.offset = offset;
		}
	}

	private String sanitizeFunctionName(String requested) {
		String cleaned = requested.replaceAll("[^A-Za-z0-9_$]", "_");
		if (cleaned.isEmpty()) {
			return "entry";
		}
		if (Character.isDigit(cleaned.charAt(0))) {
			return "fn_" + cleaned;
		}
		return cleaned;
	}

	private String formatInstruction(Instruction instr) {
		StringBuilder sb = new StringBuilder();
		sb.append(instr.getAddress()).append(": ").append(instr.getMnemonicString());
		int count = instr.getNumOperands();
		for (int i = 0; i < count; i++) {
			sb.append(i == 0 ? " " : ", ");
			sb.append(instr.getDefaultOperandRepresentation(i));
		}
		return sb.toString();
	}

	private List<EntryPoint> readEntryPoints(String[] args) throws Exception {
		List<EntryPoint> entries = new ArrayList<>();
		if (args.length < 3) {
			return entries;
		}

		Path metadata = Paths.get(args[2]).resolve(currentProgram.getName() + ".entries");
		if (!Files.isRegularFile(metadata)) {
			return entries;
		}
		for (String line : Files.readAllLines(metadata, StandardCharsets.US_ASCII)) {
			String stripped = line.trim();
			if (stripped.isEmpty()) {
				continue;
			}
			String[] fields = stripped.split("\\s+");
			if (fields.length != 2) {
				throw new IllegalArgumentException("invalid entry metadata line: " + line);
			}
			long offset = Long.decode(fields[1]);
			if (offset > 0) {
				entries.add(new EntryPoint(fields[0], offset));
			}
		}
		return entries;
	}

	private void appendDecompile(
			StringBuilder out, DecompInterface ifc, Function function) {
		DecompileResults results = ifc.decompileFunction(function, 60, monitor);
		if (results.decompileCompleted() && results.getDecompiledFunction() != null) {
			out.append(results.getDecompiledFunction().getC());
		}
		else {
			out.append("<decompile failed>\n");
			out.append(results.getErrorMessage()).append("\n");
		}
	}

	@Override
	protected void run() throws Exception {
		String[] args = getScriptArgs();
		if (args.length < 1) {
			throw new IllegalArgumentException(
				"usage: DumpV8Decompile <output-path> [function-name|AUTO] [metadata-dir]"
			);
		}
		Path requestedOutput = Paths.get(args[0]);
		boolean outputIsDirectory = Files.isDirectory(requestedOutput);
		String requestedName = args.length >= 2 ? args[1] : null;
		if ("AUTO".equals(requestedName)) {
			requestedName = null;
		}
		if (requestedName == null && outputIsDirectory) {
			requestedName = currentProgram.getName().replaceFirst("\\.bin$", "");
		}

		Address entry = currentProgram.getMinAddress();
		disassemble(entry);

		Function fn = getFunctionContaining(entry);
		if (fn == null) {
			fn = createFunction(entry, "entry");
		}
		if (fn == null) {
			throw new IllegalStateException("failed to create entry function at " + entry);
		}
		if (requestedName != null) {
			fn.setName(sanitizeFunctionName(requestedName), SourceType.USER_DEFINED);
		}

		DecompInterface ifc = new DecompInterface();
		ifc.toggleCCode(true);
		ifc.toggleSyntaxTree(true);
		if (!ifc.openProgram(currentProgram)) {
			throw new IllegalStateException("decompiler failed to open program");
		}

		StringBuilder out = new StringBuilder();
		out.append("Function: ").append(fn.getName()).append(" @ ").append(fn.getEntryPoint()).append("\n\n");
		out.append("== Listing ==\n");
		Instruction instr = getInstructionAt(fn.getEntryPoint());
		int seen = 0;
		while (instr != null && fn.getBody().contains(instr.getAddress()) && seen < 2048) {
			out.append(formatInstruction(instr)).append("\n");
			instr = instr.getNext();
			seen++;
		}

		out.append("\n== Decompile ==\n");
		appendDecompile(out, ifc, fn);

		for (EntryPoint extra : readEntryPoints(args)) {
			Address address = entry.add(extra.offset);
			if (!currentProgram.getMemory().contains(address) || getFunctionContaining(address) != null) {
				continue;
			}

			disassemble(address);
			String extraName = sanitizeFunctionName(
				fn.getName() + "_" + extra.kind + "_" + Long.toHexString(extra.offset)
			);
			Function extraFunction = createFunction(address, extraName);
			out.append("\n/* Additional ").append(extra.kind)
				.append(" entry @ ").append(address).append(" */\n");
			if (extraFunction == null) {
				out.append("<decompile failed>\nfailed to create function\n");
				continue;
			}
			appendDecompile(out, ifc, extraFunction);
		}

		Path output = outputIsDirectory
			? requestedOutput.resolve(currentProgram.getName() + ".txt")
			: requestedOutput;
		if (output.getParent() != null) {
			Files.createDirectories(output.getParent());
		}
		Files.writeString(output, out.toString(), StandardCharsets.UTF_8);
		println(out.toString());
	}
}
