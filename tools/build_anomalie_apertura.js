/* NOVICROM HUB — compila il bundle della pagina «Controllo anomalie» (apertura_segnalazione).
 *
 * Prima il JSX stava inline in <script type="text/babel"> e il browser scaricava
 * babel.min.js (3 MB) + React development (1,2 MB) per transpilarlo a OGNI apertura.
 * Ora si compila una volta qui, con lo STESSO Babel standalone e le STESSE opzioni
 * che usava il browser per i tag text/babel (presets react + env, tre plugin), così
 * il codice eseguito resta identico (env trasforma anche const/let: niente TDZ nuove).
 *
 * Uso (dalla radice del repo):  node tools/build_anomalie_apertura.js
 */
"use strict";
const fs = require("fs");
const path = require("path");

const jsDir = path.join(__dirname, "..", "django_app", "anomalie", "static", "anomalie", "js");
const src = path.join(jsDir, "src", "apertura_segnalazione.jsx");
const out = path.join(jsDir, "apertura_segnalazione.bundle.js");

const Babel = require(path.join(jsDir, "babel.min.js"));
const code = fs.readFileSync(src, "utf8");
const res = Babel.transform(code, {
  filename: "apertura_segnalazione.jsx",
  presets: ["react", "env"],
  plugins: ["transform-class-properties", "transform-object-rest-spread", "transform-flow-strip-types"],
  targets: { browsers: undefined },
});
const header = "/* eslint-disable */\n/* GENERATO da tools/build_anomalie_apertura.js da src/apertura_segnalazione.jsx: non modificare a mano. */\n";
fs.writeFileSync(out, header + res.code + "\n", "utf8");
console.log("OK", out, Buffer.byteLength(res.code), "byte");
