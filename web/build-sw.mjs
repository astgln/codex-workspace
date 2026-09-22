import {build} from 'vite';
await build({configFile:false,publicDir:false,build:{outDir:'dist',emptyOutDir:false,sourcemap:false,
 lib:{entry:'src/sw.ts',name:'WorkspacePush',formats:['iife'],fileName:()=> 'sw.js'}}});
