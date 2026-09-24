import {decode} from './envelope';
import {decodeObject} from './bundle';
import {hash} from './attachments';

export async function assembleResponse(value:unknown,records:Map<string,{revision:number;value:unknown}>):Promise<unknown>{
 const manifest=value as {payload_type?:string;parts:string[];size:number;sha256:string};
 if(manifest?.payload_type!=='parts-v1')return value;
 if(!Array.isArray(manifest.parts)||manifest.parts.length>86||!Number.isSafeInteger(manifest.size)||manifest.size<1||manifest.size>4*1024*1024)throw new Error('Некорректный размер зашифрованного ответа.');
 const bytes=new Uint8Array(manifest.size);let offset=0;
 for(const id of manifest.parts){
  const part=records.get(id)?.value as {data:string}|undefined;
  if(!part||!/^part:[a-f0-9]{64}$/.test(id))throw new Error('Ожидаем все части зашифрованного ответа.');
  const chunk=decode(part.data,48*1024);
  if(!chunk.length||id!=='part:'+await hash(chunk)||offset+chunk.length>bytes.length)throw new Error('Часть ответа изменена.');
  bytes.set(chunk,offset);offset+=chunk.length;
 }
 if(offset!==bytes.length||await hash(bytes)!==manifest.sha256)throw new Error('Ответ загружен не полностью.');
 return decodeObject(bytes);
}

