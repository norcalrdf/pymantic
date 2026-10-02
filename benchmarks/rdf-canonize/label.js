// Time rdf-canonize (RDFC-1.0) canonicalization of an N-Quads file at one
// maxWorkFactor setting, for benchmarks/compare_implementations.py. Parsing
// is done first and not timed. Prints one JSON line: {"canonize": seconds}
// or {"error": message}.
//
//   node label.js <file.nq> <maxWorkFactor or inf>
const canonize = require('rdf-canonize');
const fs = require('fs');

const workFactor = process.argv[3] === 'inf' ? Infinity : Number(process.argv[3]);
const dataset = canonize.NQuads.parse(fs.readFileSync(process.argv[2], 'utf8'));
const start = process.hrtime.bigint();
canonize.canonize(dataset, {algorithm: 'RDFC-1.0', maxWorkFactor: workFactor})
  .then(() => {
    console.log(JSON.stringify({canonize: Number(process.hrtime.bigint() - start) / 1e9}));
  })
  .catch(e => console.log(JSON.stringify({error: e.message})));
