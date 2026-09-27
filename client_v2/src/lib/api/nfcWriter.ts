// Putting content on a tag, via a writer service that is not Spoolman.
//
// Spoolman reads tags and links them to spools; it has no notion of writing one.
// Rather than fork the backend to add that, the writing lives in a small separate
// service (`nfcwriter/`) that owns the reader, and this module is the only thing
// that knows it exists. The consequence worth stating: Spoolman's Python is
// untouched, so an upstream release can be taken as-is.
//
// The division of labour is deliberate and not arbitrary:
//
//   * The writer service puts bytes on the tag and reports the UID it saw.
//   * Spoolman links that UID to the spool, through `api/tags.ts`, exactly as it
//     would for a tag added by hand.
//
// So the writer never touches the database and holds no opinion about what a tag
// means. It is a device driver with an HTTP interface. Earlier this was one
// server-side call that wrote and bound together; splitting it costs a second
// round trip and buys the whole backend staying vanilla.

// Where the writer service lives, as a path on *this* origin.
//
// It must be same-origin, and that is not a stylistic preference — an earlier
// version addressed the service directly as `http://<host>:7914` and browsers
// simply refused to send the request:
//
//     net::ERR_BLOCKED_BY_CLIENT
//
// That is not CORS, which was configured correctly and verified. It is the
// browser declining to call a bare IP:port from a page at all: ad-block and
// privacy lists carry anti-port-scanning rules matching exactly that shape, and
// private-network-access hardening and enterprise policy do the same. Measured
// side by side in one page load: `:7914/status` blocked, `/nfcwriter/status`
// returned 200. No server-side change can fix the first case, because the
// request never leaves the browser.
//
// So a reverse proxy puts both services on one origin, and this is a relative
// path. A consequence worth knowing: reaching Spoolman directly on its own port,
// bypassing the proxy, means these paths 404 and tag writing is quietly not
// offered — which is the correct behaviour, just not an obvious one.
const DEFAULT_PATH = '/nfcwriter';

function resolveBase(): string {
	const env = import.meta.env.VITE_NFC_WRITER_URL as string | undefined;
	if (env) return env.replace(/\/+$/, '');
	if (typeof window === 'undefined') return '';
	// An override for an install that proxies the service somewhere else. Still
	// expected to be same-origin; an absolute URL to another port will be blocked
	// for the reason above.
	try {
		const saved = window.localStorage.getItem('nfcWriterUrl');
		if (saved) return saved.replace(/\/+$/, '');
	} catch {
		/* storage blocked; fall through to the default */
	}
	return DEFAULT_PATH;
}

export const WRITER_BASE: string = resolveBase();

/** Whether there is a base to call at all. False only while server-rendering. */
export function writerConfigured(): boolean {
	return WRITER_BASE !== '';
}

export interface WriterStatus {
	/** The service is up and the reader is open. */
	connected: boolean;
	/** The nfcpy device the reader resolved to, for the settings screen. */
	device: string | null;
	error: string;
	transient_errors: number;
}

export interface TagFormat {
	key: string;
	label: string;
	description: string;
	/** False for UID-only formats, which bind a blank tag and write nothing. */
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

/**
 * The outcome of a write or erase. `uid` is what the reader actually saw, and is
 * the value to link — never a UID typed or remembered from somewhere else.
 */
export interface OperationResult {
	ok: boolean;
	uid: string;
	message: string;
	written_bytes: number;
	notes: string[];
}

export interface TagRecord {
	type: string;
	name: string;
	length: number;
	data_b64: string;
}

/** A tag the reader saw while nothing was armed. */
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

/**
 * A failed call to the writer service.
 *
 * Named for the writer rather than for NFC generally, because `utils/nfc.ts`
 * already exports an `NfcError` for Web NFC failures in the browser. The two are
 * unrelated — one is a service that is unreachable, the other is a phone that
 * will not scan — and sharing a name would invite catching the wrong one.
 */
export class NfcWriterError extends Error {
	constructor(
		message: string,
		readonly status: number
	) {
		super(message);
		this.name = 'NfcWriterError';
	}
}

/** Status 0, meaning the request never arrived: service down, or CORS refused it. */
export const UNREACHABLE = 0;

async function ensureOk(res: Response, what: string): Promise<Response> {
	if (res.ok) return res;
	let detail = '';
	try {
		const body = await res.json();
		detail = body?.detail ?? body?.message ?? '';
	} catch {
		/* body was not JSON; the status will have to do */
	}
	throw new NfcWriterError(detail || `${what} failed (${res.status})`, res.status);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
	let res: Response;
	try {
		res = await fetch(WRITER_BASE + path, init);
	} catch (err) {
		// A separate origin means "service is not running" and "service refused
		// this origin" both surface as a TypeError with no status. Distinguished
		// here so the dialog can say which, since the fixes are different.
		if ((err as Error)?.name === 'AbortError') throw err;
		throw new NfcWriterError(`no tag writer at ${WRITER_BASE} on this origin`, UNREACHABLE);
	}
	return (await ensureOk(res, path)).json() as Promise<T>;
}

function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
	return request<T>(path, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body),
		signal
	});
}

export function getWriterStatus(): Promise<WriterStatus> {
	return request<WriterStatus>('/status');
}

export function listTagFormats(): Promise<TagFormat[]> {
	return request<TagFormat[]>('/formats');
}

/**
 * What a format would write for a spool, and which chips have room for it.
 *
 * Only the spool's id goes over the wire. Sending the client's own spool object
 * would mean teaching the writer service the client's field names, which differ
 * from the REST ones (`filamentId` against `filament_id`, and the filament
 * nested rather than referenced) -- so the service reads the spool from
 * Spoolman's API instead and gets the exact shape the formats already expect.
 * That is one extra server-side request, against a mapping layer in two places
 * that would have to be kept in step with both.
 */
export function previewTag(spoolId: number, format: string): Promise<TagPreview> {
	return post<TagPreview>('/preview', { spool_id: spoolId, format });
}

/**
 * Write a spool to the next tag presented, and report the UID written to.
 *
 * The request stays open until a tag is dealt with or the wait times out, so
 * `signal` is how the user cancels. Unlike the integrated version this does not
 * link the UID — the caller does that through `api/tags.ts`, so that linking
 * stays Spoolman's job and stays identical to linking a tag by hand.
 */
export function writeTag(
	spoolId: number,
	format: string,
	opts: { timeout?: number; signal?: AbortSignal } = {}
): Promise<OperationResult> {
	return post<OperationResult>(
		'/write',
		{ spool_id: spoolId, format, timeout: opts.timeout ?? 60 },
		opts.signal
	);
}

/** Blank the next tag presented. Unlinking it, if wanted, is a separate step. */
export function eraseTag(opts: { timeout?: number; signal?: AbortSignal } = {}): Promise<OperationResult> {
	return post<OperationResult>('/erase', { timeout: opts.timeout ?? 60 }, opts.signal);
}

export type PowerAction = 'reboot' | 'shutdown';

export interface PowerActions {
	reboot: boolean;
	shutdown: boolean;
}

/**
 * Which power actions this host will accept.
 *
 * Asked rather than assumed: the privilege comes from a sudoers drop-in that
 * may not be installed, and offering a button that can only fail is worse than
 * not offering it.
 */
export function getPowerActions(): Promise<PowerActions> {
	return request<PowerActions>('/power');
}

/**
 * Reboot or shut down the machine Spoolman runs on.
 *
 * Resolves when the host has accepted the request, not when it has carried it
 * out -- by then this page is talking to a machine that is on its way down.
 */
export function runPowerAction(action: PowerAction): Promise<{ ok: boolean }> {
	return post<{ ok: boolean }>(`/power/${action}`, {});
}

/**
 * Subscribe to reader events. Returns a teardown function.
 *
 * The service reports reader availability as events and reconnects to the
 * hardware underneath, so this stays open across an unplug instead of the
 * browser retrying in a loop of its own.
 */
export function subscribeToWriter(onEvent: (event: TagEvent) => void): () => void {
	const source = new EventSource(WRITER_BASE + '/events');
	source.onmessage = (e) => {
		try {
			onEvent(JSON.parse(e.data) as TagEvent);
		} catch {
			/* a frame we cannot read is not worth breaking the stream over */
		}
	};
	return () => source.close();
}
