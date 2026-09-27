import {
	getWriterStatus,
	listTagFormats,
	subscribeToWriter,
	writerConfigured,
	type TagEvent,
	type TagFormat
} from '$lib/api/nfcWriter';
import type { Spool } from '$lib/types';

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

	/**
	 * A tag tapped while nothing was expecting one. Drives the tag-found dialog.
	 */
	tag = $state<TagEvent | null>(null);

	/** The spool whose write dialog is open, if any. */
	writeFor = $state<Spool | null>(null);

	// A tag left resting on the reader keeps being detected -- the reader polls
	// and cannot say "still the same one". So a tag the user has already dealt
	// with is remembered and ignored until a different one turns up, which is
	// what stops the dialog reopening every few seconds. The service suppresses
	// repeat *forwards* to Spoolman for the same reason, but it cannot know that
	// this browser has dismissed a dialog, so the two are not redundant.
	#handled = $state<string | null>(null);

	// Set while a dialog is driving the reader itself. An ambient tap is ignored
	// then: the tag on the reader is the one being written, and announcing it as
	// a discovery over the top of that would be nonsense.
	#claims = $state(0);

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

	/** Start listening for reader events. Returns a teardown function. */
	start(): () => void {
		if (!this.available) return () => {};
		return subscribeToWriter((event) => this.#handle(event));
	}

	#handle(event: TagEvent) {
		if (event.type === 'reader_status') {
			this.connected = !!event.connected;
			this.error = event.error ?? '';
			return;
		}
		if (event.type !== 'tag' || !event.uid) return;
		if (this.#claims > 0) return;
		if (event.uid === this.#handled) return;
		// Already on screen: re-setting it would restart the owner lookup for a
		// tag the user is currently looking at.
		if (this.tag?.uid === event.uid) return;
		this.tag = event;
	}

	/**
	 * Take the reader for a dialog. Returns the matching release, so a caller can
	 * hand it straight to a teardown and never have to pair the calls itself.
	 */
	claim(): () => void {
		this.#claims += 1;
		let released = false;
		return () => {
			if (released) return;
			released = true;
			this.#claims = Math.max(0, this.#claims - 1);
		};
	}

	/** Dismiss the tag-found dialog, and stop this tag raising it again. */
	dismissTag() {
		this.#handled = this.tag?.uid ?? this.#handled;
		this.tag = null;
	}

	/**
	 * Treat a tag as dealt with without it having been shown -- used after writing
	 * or erasing one, which otherwise leaves it sitting on the reader waiting to
	 * be announced as a fresh discovery.
	 */
	suppress(uid: string) {
		if (uid) this.#handled = uid;
	}

	/** Open the write dialog for a spool, from wherever. */
	openWrite(spool: Spool) {
		this.writeFor = spool;
	}

	closeWrite() {
		this.writeFor = null;
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
