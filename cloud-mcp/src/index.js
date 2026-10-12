import { handleMcp, handleSync, handleLiveRegister } from './mcp.js';
import { handleRest } from './rest.js';
import { handleHighnesShare, handleHighnesSync, highnesCalendarIcs } from './highnes.js';

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, '') || '/';

    if (path.startsWith('/api')) {
      return handleRest(request, env);
    }

    if (path === '/health') {
      return new Response(
        JSON.stringify({
          ok: true,
          service: 'expense-tracker-mcp-hub',
          build: '2026-08-22-v1.4.9-resilient-live-fallback',
          mcp: '/mcp?key=YOUR_MCP_KEY',
          app: '/app/?key=YOUR_MCP_KEY',
          sync: 'POST /sync with X-Sync-Key or ?key=',
        }),
        { headers: { 'Content-Type': 'application/json' } },
      );
    }

    if (path === '/mcp') {
      return handleMcp(request, env);
    }

    if (path === '/sync') {
      return handleSync(request, env);
    }

    if (path === '/sync/live') {
      return handleLiveRegister(request, env);
    }

    if (path === '/sync/highnes') {
      return handleHighnesSync(request, env);
    }

    if (path === '/share/highnes/calendar.ics') {
      return handleHighnesShare(request, env, { calendar: true, ics: highnesCalendarIcs });
    }

    if (path === '/share/highnes') {
      return handleHighnesShare(request, env);
    }

    if (path === '/') {
      const dest = new URL('/app/', request.url);
      return Response.redirect(dest, 302);
    }

    if (env.ASSETS) {
      const resp = await env.ASSETS.fetch(request);
      if (path === '/app' || path.endsWith('.html') || path.endsWith('/sw.js') || path === '/app/sw.js') {
        const headers = new Headers(resp.headers);
        headers.set('Cache-Control', 'no-cache, no-store, must-revalidate');
        headers.set('Pragma', 'no-cache');
        headers.set('Expires', '0');
        return new Response(resp.body, {
          status: resp.status,
          statusText: resp.statusText,
          headers,
        });
      }
      return resp;
    }

    return new Response(
      JSON.stringify({ error: 'Not found', paths: ['/health', '/app/', '/api/health', '/mcp', '/sync'] }),
      { status: 404, headers: { 'Content-Type': 'application/json' } },
    );
  },
};
