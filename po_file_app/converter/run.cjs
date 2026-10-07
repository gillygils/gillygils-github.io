// Local adapter. Third-party modules are downloaded separately, not distributed here.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const crypto = require('node:crypto');
const {TextEncoder,TextDecoder} = require('node:util');

async function convert(source, destination) {
  if (!/\.sldprt$/i.test(source)) throw Error('Only .sldprt part conversion is supported.');
  if (fs.existsSync(destination)) throw Error('Destination already exists; it will not be overwritten.');
  if (fs.statSync(source).size > 64 * 1024 * 1024) throw Error('Part exceeds the 64 MiB initial converter limit.');
  const input = fs.readFileSync(source);
  const manifest = JSON.parse(fs.readFileSync(path.join(__dirname,'manifest.json'),'utf8'));
  const sandbox = {
    console, TextEncoder, TextDecoder, URL, Blob, Buffer, crypto:webcrypto,
    Uint8Array, Uint16Array, Uint32Array, Int8Array, Int16Array, Int32Array,
    Float32Array, Float64Array, ArrayBuffer, DataView, BigInt64Array, BigUint64Array,
    atob, btoa, setTimeout, clearTimeout, queueMicrotask, performance,
    fetch:async()=>{throw Error('Network requests are disabled during local conversion.');}
  };
  sandbox.self = sandbox;
  const modules = {};
  sandbox.webpackChunk_N_E = [];
  sandbox.webpackChunk_N_E.push = chunk => {Object.assign(modules,chunk[1]);return 0;};
  const context = vm.createContext(sandbox);
  for (const file of manifest.files) {
    const bytes = fs.readFileSync(path.join(__dirname,'..','.converter','modules',file.name));
    if (crypto.createHash('sha256').update(bytes).digest('hex') !== file.sha256) throw Error('Converter checksum mismatch: '+file.name);
    vm.runInContext(bytes.toString('utf8'),context,{filename:file.name,timeout:10000});
  }
  const cache = {};
  function load(id) {
    if(cache[id])return cache[id].exports;
    if(!modules[id])throw Error('Missing converter module '+id);
    const item={exports:{}}; cache[id]=item;
    modules[id](item,item.exports,load);
    return item.exports;
  }
  load.d=(target,defs)=>{for(const key in defs)Object.defineProperty(target,key,{enumerable:true,get:defs[key]});};
  load.r=target=>Object.defineProperty(target,'__esModule',{value:true});
  load.n=mod=>{const get=mod&&mod.__esModule?()=>mod.default:()=>mod;load.d(get,{a:get});return get;};
  load.o=(obj,key)=>Object.prototype.hasOwnProperty.call(obj,key);
  load.g=sandbox;
  load.e=async id=>{throw Error('Unsupported dynamic converter component '+id);};
  load.U=URL;
  const Reader=Object.values(load(manifest.reader_module)).find(value=>typeof value==='function'&&value.supportedFormats?.includes('sldprt'));
  if(!Reader)throw Error('The pinned converter does not expose a compatible SolidWorks reader.');
  const outputs=await new Reader().execute({
    files:[{fileName:path.basename(source),buffer:new Uint8Array(input)}],
    outputFormat:'stp',progressCallback:(progress,message)=>console.log(JSON.stringify({progress,message}))
  });
  if(outputs.length!==1)throw Error('Expected exactly one STEP result.');
  const result=Buffer.from(outputs[0].buffer);
  if(!result.toString('ascii',0,30).startsWith('ISO-10303-21;')||!result.includes(Buffer.from('END-ISO-10303-21;')))throw Error('Converter did not produce a complete STEP file.');
  fs.writeFileSync(destination,result,{flag:'wx'});
  console.log(JSON.stringify({success:true,bytes:result.length,geometry_source:outputs[0].geometrySource}));
}
if(process.argv.length!==4){console.error('Usage: node run.cjs source.sldprt output.step');process.exitCode=1;}
else convert(process.argv[2],process.argv[3]).catch(error=>{console.error(error.message);process.exitCode=1;});
