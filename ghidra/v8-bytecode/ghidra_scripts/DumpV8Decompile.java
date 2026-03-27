//@category V8Bytecode

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;

public class DumpV8Decompile extends GhidraScript {

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

	@Override
	protected void run() throws Exception {
		String[] args = getScriptArgs();
		if (args.length < 1) {
			throw new IllegalArgumentException("usage: DumpV8Decompile <output-path>");
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

		DecompInterface ifc = new DecompInterface();
		ifc.toggleCCode(true);
		ifc.toggleSyntaxTree(true);
		if (!ifc.openProgram(currentProgram)) {
			throw new IllegalStateException("decompiler failed to open program");
		}

		DecompileResults res = ifc.decompileFunction(fn, 60, monitor);

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
		if (res.decompileCompleted() && res.getDecompiledFunction() != null) {
			out.append(res.getDecompiledFunction().getC());
		}
		else {
			out.append("<decompile failed>\n");
			out.append(res.getErrorMessage()).append("\n");
		}

		Path output = Paths.get(args[0]);
		Files.createDirectories(output.getParent());
		Files.writeString(output, out.toString(), StandardCharsets.UTF_8);
		println(out.toString());
	}
}
