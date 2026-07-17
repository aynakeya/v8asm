"use strict";

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root =
  process.env.V8_CACHE_DUMP_DIR || path.join(process.cwd(), "v8-cache-dump");
const output = path.join(root, String(process.pid));
fs.mkdirSync(output, { recursive: true });

const OriginalScript = vm.Script;
let sequence = 0;

function asBuffer(value) {
  if (Buffer.isBuffer(value)) return value;
  return Buffer.from(value.buffer, value.byteOffset, value.byteLength);
}

function report(error) {
  process.stderr.write(`[v8-cache-capture] ${error.stack || error}\n`);
}

function extractPayload(cache) {
  const pointerSize = process.arch === "ia32" || process.arch === "arm" ? 4 : 8;
  const layouts = [
    { lengthOffset: 20, unalignedHeaderSize: 28 },
    { lengthOffset: 16, unalignedHeaderSize: 24 },
  ];
  const candidates = layouts.flatMap(({ lengthOffset, unalignedHeaderSize }) => {
    const headerSize =
      Math.ceil(unalignedHeaderSize / pointerSize) * pointerSize;
    if (cache.length < headerSize || cache.length < lengthOffset + 4) return [];
    const payloadSize = cache.readUInt32LE(lengthOffset);
    if (payloadSize !== cache.length - headerSize) return [];
    return [{ headerSize, payloadSize }];
  });
  if (candidates.length !== 1) return null;
  const [{ headerSize, payloadSize }] = candidates;
  return {
    offset: headerSize,
    data: cache.subarray(headerSize, headerSize + payloadSize),
  };
}

vm.Script = new Proxy(OriginalScript, {
  construct(target, args, newTarget) {
    const options = args[1];
    const cachedData =
      options && typeof options === "object" ? options.cachedData : undefined;
    if (!cachedData) return Reflect.construct(target, args, newTarget);

    const id = String(sequence++).padStart(4, "0");
    const prefix = path.join(output, id);
    const input = asBuffer(cachedData);
    try {
      fs.writeFileSync(`${prefix}.input.jsc`, input);
    } catch (error) {
      report(error);
    }

    const script = Reflect.construct(target, args, newTarget);
    const metadata = {
      pid: process.pid,
      sequence: Number(id),
      v8_version: process.versions.v8,
      filename:
        typeof options.filename === "string" ? options.filename : null,
      input_size: input.length,
      cached_data_rejected: script.cachedDataRejected,
      normalized_size: null,
      payload_offset: null,
      payload_size: null,
    };

    if (!script.cachedDataRejected) {
      try {
        const normalized = script.createCachedData();
        metadata.normalized_size = normalized.length;
        fs.writeFileSync(`${prefix}.normalized.jsc`, normalized);
        const payload = extractPayload(normalized);
        if (payload) {
          metadata.payload_offset = payload.offset;
          metadata.payload_size = payload.data.length;
          fs.writeFileSync(`${prefix}.payload.bin`, payload.data);
        }
      } catch (error) {
        report(error);
      }
    }
    try {
      fs.writeFileSync(
        `${prefix}.json`,
        `${JSON.stringify(metadata, null, 2)}\n`
      );
    } catch (error) {
      report(error);
    }
    return script;
  },
});
