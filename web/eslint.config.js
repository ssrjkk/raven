import tsParser from "@typescript-eslint/parser";
import simpleImportSort from "eslint-plugin-simple-import-sort";

export default [
  { ignores: ["dist/", "node_modules/"] },
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: { parser: tsParser },
    plugins: { "simple-import-sort": simpleImportSort },
    rules: {
      "simple-import-sort/imports": "error",
      "simple-import-sort/exports": "error",
    },
  },
];
