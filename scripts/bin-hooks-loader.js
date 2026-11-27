import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

export function load(url, context, nextLoad) {
  if (url.endsWith(".bin")) {
    const data = readFileSync(fileURLToPath(url));
    const source =
      "export default Uint8Array.from(Buffer.from(" +
      JSON.stringify(data.toString("base64")) +
      ', "base64"));\n';
    return { format: "module", source, shortCircuit: true };
  }
  return nextLoad(url, context);
}
