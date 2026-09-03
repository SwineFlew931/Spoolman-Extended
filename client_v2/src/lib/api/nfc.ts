import { API_BASE } from './config';

// NFC reader endpoints. These talk to Spoolman, which talks to the reader
// daemon — the browser never addresses the reader directly, so there is no
// second host to configure and no cross-origin story to get wrong.

export interface NfcStatus {
	enabled: boolean;
	connected: boolean;
	device: string | null;
	error: string;
	transient_errors: number;
}

export interface TagFormat {
	key: string;
	label: string;
	description: string;
	writes_tag: boolean;
}

export interface ChipRecommendation {
	name: string;
	capacity: number;
	fits: boolean;
	headroom: number;
}

export interface TagPreview {
	format: string;
	writes_tag: boolean;
	record_type: string;
	size: number;
	notes: string[];
	recommended: ChipRecommendation[];
}

export interface OperationResult {
	ok: boolean;
	uid: string;
	message: string;
	written_bytes: number;
	bound: boolean;
	unbound_from: number | null;
	notes: string[];
}

export interface UidOwner {
	uid: string;
	free: boolean;
	spool_id: number | null;
	spool_name: string;
	archived: boolean;
}

export interface TagRecord {
	type: string;
	name: string;
	length: number;
	data_b64: string;
}

/** A tag seen by the reader when nothing was armed. */
export interface TagEvent {
	type: string;
	uid?: string;
	records?: TagRecord[];
	blank?: boolean;
	capacity?: number | null;
	writeable?: boolean | null;
	connected?: boolean;
	error?: string;
}

/** A non-2xx response from an NFC endpoint, carrying the server's own wording. */
export class NfcError extends Error {
	constructor(
		message: string,
		readonly status: number
	) {
		super(message);
		this.name = 'NfcError';
	}
}

// The shared http.ts helper reads `message` from an error body; FastAPI's
// HTTPException writes `detail`. Both are read here so a refused write explains
// itself in the dialog instead of showing a bare status code.
async function ensureOk(res: Response, what: string): Promise<Response> {
	if (res.ok) return res;
	let detail = '';
	try {
		const body = await res.json();
		detail = body?.detail ?? body?.message ?? '';
	} catch {
		/* body was not JSON; the status will have to do */
	}
	throw new NfcError(detail || `${what} failed (${res.status})`, res.status);
}

async function get<T>(path: string): Promise<T> {
	return (await ensureOk(await fetch(API_BASE + path), path)).json() as Promise<T>;
}

async function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
	const res = await fetch(API_BASE + path, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body),
		signal
	});
	return (await ensureOk(res, path)).json() as Promise<T>;
}

export function getNfcStatus(): Promise<NfcStatus> {
	return get<NfcStatus>('/nfc/status');
}

export function listTagFormats(): Promise<TagFormat[]> {
	return get<TagFormat[]>('/nfc/formats');
}

/** What a format would write for a spool, and which chips would hold it. */
export function previewTag(spoolId: number, format: string): Promise<TagPreview> {
	return post<TagPreview>('/nfc/preview', { spool_id: spoolId, format });
}

/**
 * Write a spool to the next tag presented. The request stays open until the tag
 * is dealt with or the wait times out, so the binding happens server-side in the
 * same place that saw the write succeed. Pass a signal to let the user cancel.
 */
export function writeTag(
	spoolId: number,
	format: string,
	opts: { bind?: boolean; timeout?: number; signal?: AbortSignal } = {}
): Promise<OperationResult> {
	return post<OperationResult>(
		'/nfc/write',
		{ spool_id: spoolId, format, bind: opts.bind ?? true, timeout: opts.timeout ?? 60 },
		opts.signal
	);
}

/** Blank the next tag presented, optionally freeing its UID from whatever holds it. */
export function eraseTag(
	opts: { unbind?: boolean; timeout?: number; signal?: AbortSignal } = {}
): Promise<OperationResult> {
	return post<OperationResult>(
		'/nfc/erase',
		{ unbind: opts.unbind ?? true, timeout: opts.timeout ?? 60 },
		opts.signal
	);
}

/** Which spool holds this UID, archived spools included. */
export function lookupUid(uid: string): Promise<UidOwner> {
	return get<UidOwner>(`/nfc/uid/${encodeURIComponent(uid)}`);
}

/** Remove one UID from a spool. The tag itself is left alone. */
export async function unbindUid(spoolId: number, uid: string): Promise<string[]> {
	const res = await fetch(API_BASE + `/nfc/spool/${spoolId}/uid/${encodeURIComponent(uid)}`, {
		method: 'DELETE'
	});
	return (await ensureOk(res, 'unbind')).json() as Promise<string[]>;
}

/**
 * Subscribe to reader events. Returns a teardown function.
 *
 * The stream reports reader availability as events and reconnects underneath, so
 * this stays open across an unplug rather than the browser reconnecting in a
 * loop of its own.
 */
export function subscribeToTags(onEvent: (event: TagEvent) => void): () => void {
	const source = new EventSource(API_BASE + '/nfc/events');
	source.onmessage = (e) => {
		try {
			onEvent(JSON.parse(e.data) as TagEvent);
		} catch {
			/* a frame we cannot read is not worth breaking the stream over */
		}
	};
	return () => source.close();
}

/**
 * Read a spool's bound tag UIDs out of its extra fields.
 *
 * Extra values are JSON-encoded strings, so `card_uids` arrives as
 * `'"04BA1457D32A81,04B9..."'` — quotes included — and has to be decoded before
 * it can be split.
 */
export function parseCardUids(extra: Record<string, string> | undefined): string[] {
	const raw = extra?.card_uids;
	if (!raw) return [];
	let value: unknown = raw;
	try {
		value = JSON.parse(raw);
	} catch {
		/* written by something that did not encode it; take it as text */
	}
	if (typeof value !== 'string' || !value) return [];
	return value
		.split(',')
		.map((part) => part.trim().toUpperCase())
		.filter(Boolean);
}
