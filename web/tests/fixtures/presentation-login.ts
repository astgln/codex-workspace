/** Only presentation specs import this, via a Playwright module route. */
import {restoreSession} from '../../src/shared/api/transport';
export const prepareLogin=async()=>({devices:[]});
export const login=async()=>{await fetch('/web/login/session',{method:'POST',body:'{}'});return restoreSession();};
export const loginDevice=login;

export const authenticateDevice=login;
