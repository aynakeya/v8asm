function parseLine(line) {
  const match = /^(\w+):(\d+)$/u.exec(line);
  if (!match) {
    return `bad:${line}`;
  }
  return `${match[1].toUpperCase()}=${Number(match[2]) + 1}`;
}

parseLine("id:41");
