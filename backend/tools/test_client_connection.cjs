// Run: node tools/test_client_connection.cjs
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict'), path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/static/app.js'), 'utf8');
const block = source.slice(source.indexOf('let wsRetryTimer = null;'), source.indexOf('\nfunction send('));
const sockets = [], retries = [];
class Socket {
  constructor() { sockets.push(this); }
  close() { this.closed = true; if (this.onclose) this.onclose({code:1000}); }
}
const ctx = vm.createContext({WebSocket:Socket,location:{protocol:'https:',host:'local'},Math,JSON,encodeURIComponent,
  setTimeout:fn=>{retries.push(fn);return retries.length;},clearTimeout:()=>{},setConnBanner:()=>{},toast:()=>{},go:()=>{},render:()=>{}});
vm.runInContext('let ws=null, gameId="g", sessionToken="t", wsRetryDelay=1500, currentState=null;'+block,ctx);
vm.runInContext('connectWS(); connectWS();',ctx);
assert.equal(sockets[0].closed,true);
assert.equal(retries.length,0,'Replacing a connection must not schedule a retry');
sockets[1].onmessage({data:'not JSON'});
sockets[1].onclose({code:4401});
assert.equal(retries.length,0,'Expired credentials must not retry forever');
vm.runInContext('connectWS()',ctx);
sockets[2].onclose({code:1006});
assert.equal(retries.length,1,'Unexpected disconnect should retry');
vm.runInContext('connectWS()',ctx);
sockets[3].onmessage({data:JSON.stringify({type:'game_stopped'})});
assert.equal(vm.runInContext('gameId',ctx),null);
assert.equal(sockets[3].closed,true);
console.log('Client connection regressions: passed');
