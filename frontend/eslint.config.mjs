import next from "eslint-config-next";

export default [
  ...(Array.isArray(next) ? next : [next]),
  { ignores: [".next/**", "node_modules/**", "public/sw.js"] },
];
