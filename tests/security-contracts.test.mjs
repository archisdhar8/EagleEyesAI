import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root=path.resolve(import.meta.dirname,"..");

test("secret files are ignored and browser env contains only publishable Supabase values",()=>{
  const ignore=fs.readFileSync(path.join(root,".gitignore"),"utf8");
  assert.match(ignore,/^\.env$/m);assert.match(ignore,/^\.env\.\*$/m);
  const example=fs.readFileSync(path.join(root,".env.example"),"utf8");
  const publicNames=[...example.matchAll(/^([A-Z0-9_]+)=/gm)].map(match=>match[1]).filter(name=>name.startsWith("NEXT_PUBLIC_"));
  assert.deepEqual(publicNames.sort(),["NEXT_PUBLIC_API_URL","NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY","NEXT_PUBLIC_SUPABASE_URL"].sort());
  assert.doesNotMatch(example,/sb_secret_|service_role|postgres(?:ql)?:\/\/[^\s]*:[^\s]*@/i);
});
