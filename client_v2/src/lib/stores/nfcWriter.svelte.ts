import {
	getWriterStatus,
	listTagFormats,
	subscribeToWriter,
	writerConfigured,
	type TagFormat
} from '$lib/api/nfcWriter';

// Whether a tag writer is available, and what it can write.
//
// Deliberately smaller than it looks like it should be. Two jobs that the
// integrated version did here have moved elsewhere, and neither needed to be in
// the client:
//
//   * Announcing a tag tapped when nothing expected one. Spoolman does this
//     itself now — the writer service forwards ambient taps to `/tag/scan` like
//     any other reader, and `scanRelay` takes it from there. That is better than
//     what this replaced: a paired browser jumps straight to the spool.
//   * Claiming the reader so a write in progress is not also reported as an
//     ambient scan. The service knows when it is armed, so it simply does not
//     forward those taps. A client-side flag could only ever have been an
//     approximation of that.
//
// What is left is status, which every NFC affordance needs in order to decide
// whether to render at all.

class NfcWriterState {
	/** A writer service is configured and answered. */
	available = $state(false);
	/** It answered, and its reader is open. */
	connected = $state(false);
	error = $state('');
	formats = $state<TagFormat[]>([]);
	/** False until the first probe settles, so nothing flickers on load. */
	loaded = $state(false);

	/** The format last written with, offered as the default next time. */
	lastFormat = $state<string | null>(null);

	get usable(): boolean {
		return this.available && this.connected;
	}

	async load() {
		if (!writerConfigured()) {
			this.loaded = true;
			return;
		}
		try {
			const [status, formats] = await Promise.all([getWriterStatus(), listTagFormats()]);
			this.available = true;
			this.connected = status.connected;
			this.error = status.error;
			this.formats = formats;
		} catch (e) {
			// No writer service is the normal case for a plain Spoolman install, not
			// an error. Tag writing is simply not offered.
			console.debug('NFC writer unavailable', e);
			this.available = false;
			this.connected = false;
		} finally {
			this.loaded = true;
		}
	}

	/** Start listening for reader status. Returns a teardown function. */
	start(): () => void {
		if (!this.available) return () => {};
		return subscribeToWriter((event) => {
			if (event.type !== 'reader_status') return;
			this.connected = !!event.connected;
			this.error = event.error ?? '';
		});
	}

	/**
	 * Remember a format choice, so writing a second spool does not mean picking
	 * the same format again. Persisted per browser: a workshop tends to standardise
	 * on one format, and re-choosing it every time is the kind of friction that
	 * makes people stop using a feature.
	 */
	rememberFormat(key: string) {
		this.lastFormat = key;
		try {
			window.localStorage.setItem('nfcWriterFormat', key);
		} catch {
			/* storage blocked; the choice just will not outlive the tab */
		}
	}

	restoreFormat() {
		try {
			this.lastFormat = window.localStorage.getItem('nfcWriterFormat');
		} catch {
			/* storage blocked; no remembered choice */
		}
	}

	formatLabel(key: string): string {
		return this.formats.find((f) => f.key === key)?.label ?? key;
	}
}

export const nfcWriter = new NfcWriterState();
