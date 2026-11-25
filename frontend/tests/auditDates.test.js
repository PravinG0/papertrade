import test from 'node:test';
import assert from 'node:assert/strict';
import {istParts,dateTimeIST,dateInRange,todayIST} from '../src/utils/tradeDates.js';
for (const [input,expected] of [
 ['2026-11-24T18:29:59Z','24/11/2026 23:59:59'],
 ['2026-11-24T18:30:00Z','25/11/2026 00:00:00'],
 ['2026-11-25 09:15','25/11/2026 09:15:00'],
 ['2026-11-25 15:15:00.123','25/11/2026 15:15:00'],
 ['2026-11-25T00:00:00-05:00','25/11/2026 10:30:00'],
]) test(`IST conversion ${input}`,()=>assert.equal(dateTimeIST(input),expected));
for(const input of ['',null,undefined,'invalid','2026-11-25']) test(`missing time ${input}`,()=>assert.equal(istParts(input),null));
for(const input of ['2026-02-30 12:00:00','2026-13-01 12:00:00','2026-11-25 25:00:00','2026-11-25 10:65:00']) test(`reject impossible timestamp ${input}`,()=>assert.equal(istParts(input),null));
for(const [input,from,to,expected] of [
 ['2026-11-25 00:00:00','2026-11-25','2026-11-25',true],
 ['2026-11-25 23:59:59','2026-11-25','2026-11-25',true],
 ['2026-11-24 23:59:59','2026-11-25','',false],
 ['2026-11-26 00:00:00','','2026-11-25',false],
 ['2026-11-25 12:00:00','2026-11-26','2026-11-24',false],
 ]) test(`date bounds ${input} ${from} ${to}`,()=>assert.equal(dateInRange(input,from,to),expected));
test('today format',()=>assert.match(todayIST(),/^\d{4}-\d{2}-\d{2}$/));
for(const input of ['2026-02-30T12:00:00Z','2026-11-31T12:00:00+05:30','2026-11-25T24:00:00Z','2026-11-25T10:00:60Z']) test(`reject invalid offset calendar ${input}`,()=>assert.equal(istParts(input),null));
test('valid leap day',()=>assert.equal(dateTimeIST('2024-02-29 12:00:00'),'29/02/2024 12:00:00'));
