// Vercel Edge Middleware — HTTP Basic Auth gate for the whole site.
//
// Password: set DASH_USER / DASH_PASS in Vercel → Project → Settings →
// Environment Variables to override the defaults below. If you don't set them,
// the login is  user: sam  /  password: samsam .
//
// NOTE: this repo is public, so the fallback password is visible here. For a
// private password, add the env vars in Vercel and redeploy.

export const config = {
  // Protect everything except Vercel internals and the favicon.
  matcher: ['/((?!_next/|_vercel/|favicon.ico).*)'],
};

export default function middleware(request) {
  const USER = process.env.DASH_USER || 'sam';
  const PASS = process.env.DASH_PASS || 'samsam';

  const header = request.headers.get('authorization') || '';
  const [scheme, encoded] = header.split(' ');

  if (scheme === 'Basic' && encoded) {
    let decoded = '';
    try { decoded = atob(encoded); } catch (e) { decoded = ''; }
    const i = decoded.indexOf(':');
    const u = decoded.slice(0, i);
    const p = decoded.slice(i + 1);
    if (u === USER && p === PASS) {
      return; // authorised — continue to the static file
    }
  }

  return new Response('Authentication required.', {
    status: 401,
    headers: {
      'WWW-Authenticate': 'Basic realm="Leads Dashboard", charset="UTF-8"',
    },
  });
}
