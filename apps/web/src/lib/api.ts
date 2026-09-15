function apiBase():string { return process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "/api/v1"; }

async function request(path:string,init?:RequestInit):Promise<Response>{
  return fetch(`${apiBase()}${path}`,{...init,credentials:"include",headers:{"Content-Type":"application/json",...init?.headers}});
}

export async function api<T>(path:string,init?:RequestInit):Promise<T>{
  let response=await request(path,init);
  if(response.status===401 && path!=="/auth/refresh" && path!=="/auth/login" && path!=="/auth/register"){
    const refreshed=await request("/auth/refresh",{method:"POST"});
    if(refreshed.ok) response=await request(path,init);
  }
  if(!response.ok)throw new Error((await response.json().catch(()=>({detail:"Falha de comunicação"}))).detail);
  return response.status===204?undefined as T:response.json();
}
