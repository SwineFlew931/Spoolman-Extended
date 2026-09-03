import { redirect } from '@sveltejs/kit';
import { resolve } from '$app/paths';
import type { PageLoad } from './$types';

// The short form of /spool/show/<id>, for NFC tags. OpenTag3D's online_url
// field is 32 bytes, and "http://192.168.0.165:7912/spool/show/26" is 39 — long
// enough that it would be written truncated, leaving a URL that resolves to the
// wrong place. "http://192.168.0.165:7912/s/26" is 30 and fits, so tags carry
// this route and it lands where the long one would have.
//
// Not prerenderable (dynamic id); the SPA fallback boots the app and this load
// runs the client-side redirect.
export const prerender = false;

export const load: PageLoad = ({ params }) => {
	redirect(307, resolve(`/?sel=spool:${params.id}`));
};
