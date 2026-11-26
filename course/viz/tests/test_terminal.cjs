/* Regression tests run against the viewer's real renderer, without exporting a test API. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../viewer/mode-terminal.js'),'utf8');
const hook="  window.CVIZ_MODES.register('terminal',";
assert(source.includes(hook));
const sandbox={window:{CVIZ_MODES:{register(){}}},location:{search:''},URLSearchParams};
vm.runInNewContext(source.replace(hook,'  globalThis.renderPlainForTest=plain;\n'+hook),sandbox);
const plain=sandbox.renderPlainForTest;
test('short carriage-return redraw discards the old tail',()=>{
 assert.equal(plain('Downloading 100%\rDone'),'Done');
 assert.equal(plain('long progress\rshort\rOK\n'),'OK\n');
});
test('CRLF and a trailing carriage return keep completed text',()=>{
 assert.equal(plain('hello\r\nworld\r\n'),'hello\nworld\n');
 assert.equal(plain('hello\r'),'hello');
});
test('erase-in-line default and zero erase from cursor to end',()=>{
 assert.equal(plain('abcdef\b\b\x1b[KZ'),'abcdZ');
 assert.equal(plain('abcdef\b\b\x1b[0K'),'abcd');
});
test('erase-in-line one and two preserve cursor position',()=>{
 assert.equal(plain('abcdef\b\b\x1b[1K'),'     f');
 assert.equal(plain('abcdef\b\b\x1b[2KZ'),'    Z');
});
test('colour and terminal title sequences do not corrupt progress text',()=>{
 assert.equal(plain('\x1b]0;Demo\x07\x1b[32mlong progress\x1b[0m\rOK\x1b[K\r\n'),'OK\n');
});
test('terminal string terminators preserve output between consecutive OSC sequences',()=>{
 assert.equal(plain('\x1b]0;First\x1b\\alpha\x1b]0;Second\x1b\\beta\n'),'alphabeta\n');
 assert.equal(plain('\x1b]0;First\x1b\\alpha\x1b]0;Second\x07beta\n'),'alphabeta\n');
});
test('a bare escape in an OSC payload does not end the sequence',()=>{
 assert.equal(plain('before\x1b]0;title\x1bpart\x07after'),'beforeafter');
 assert.equal(plain('before\x1b]0;title\x1bpart\x1b\\'),'before');
});
