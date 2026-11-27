import { register } from "node:module";
import { pathToFileURL } from "node:url";

register(new URL("./bin-hooks-loader.js", import.meta.url));
