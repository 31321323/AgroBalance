export async function api<T>(path:string, method='GET', data?:unknown):Promise<T>{
  let response:Response
  try { response=await fetch('/api'+path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)}) }
  catch { throw new Error('Нет связи с сервером. Проверьте подключение и повторите.') }
  const body=await response.json().catch(()=>({detail:'Сервер вернул некорректный ответ'}))
  if(!response.ok){
    const detail=Array.isArray(body.detail)?body.detail.map((e:{loc:string[];msg:string})=>`${e.loc.slice(1).join('.')}: ${e.msg}`).join('; '):body.detail
    throw new Error(detail||'Не удалось выполнить запрос')
  }
  return body
}
export const n=(x:number|undefined|null, digits=1)=>x==null?'—':new Intl.NumberFormat('ru-RU',{maximumFractionDigits:digits}).format(x)
export const localDay=(zone='Europe/Chisinau')=>new Intl.DateTimeFormat('sv-SE',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())
export const dateLabel=(x:string, full=false)=>new Date(x+'T12:00:00').toLocaleDateString('ru-RU',{day:'numeric',month:full?'long':'short'})
