import { getNfcStatus, listTagFormats, subscribeToTags, type TagEvent, type TagFormat } from '$lib/api/nfc';

// Reader state, shared by everything that cares whether a tag reader is there.
//
// One subscription is held for the whole app (started by the root layout), and
// it does two jobs: keeping the reader indicator honest, and noticing tags
// tapped when nothing in particular was expecting one. That second job is what
// raises the "this tag is already known" dialog, so it has to be listening even
// when no dialog is open.

class NfcState {
	enabled = $state(false);
	connected = $state(false);
	error = $state('');
	formats = $state<TagFormat[]>([]);
	loaded = $state(false);

	/** A tag tapped while nothing was being written. Drives the tag-found dialog. */
	tag = $state<TagEvent | null>(null);

	// A tag left resting on the reader keeps being detected — the reader has no
	// way to say "still the same one", and suppressing re-taps for longer would
	// make a deliberate second tap feel broken. So a tag the user has already
	// dealt with is remembered and ignored until a different one turns up, which
	// is what stops the dialog reopening every few seconds.
	private handled = $state<string | null>(null);

	// Set while a dialog is driving the reader itself. Ambient taps are ignored
	// then: the tag on the reader is the one being written, and popping "this tag
	// is already known" over the write in progress would be nonsense.
	private claims = $state(0);

	get busy(): boolean {
		return this.claims > 0;
	}

	/** Whether the reader is usable right now. */
	get available(): boolean {
		return this.enabled && this.connected;
	}

	async load() {
		try {
			const [status, formats] = await Promise.all([getNfcStatus(), listTagFormats()]);
			this.enabled = status.enabled;
			this.connected = status.connected;
			this.error = status.error;
			this.formats = formats;
		} catch (e) {
			// A server without the NFC endpoints is a normal thing to be talking to;
			// it just means no reader features, not a broken page.
			console.debug('NFC status unavailable', e);
			this.enabled = false;
			this.connected = false;
		} finally {
			this.loaded = true;
		}
	}

	/** Start listening. Returns a teardown function for the layout's effect. */
	start(): () => void {
		return subscribeToTags((event) => this.handle(event));
	}

	private handle(event: TagEvent) {
		if (event.type === 'reader_status') {
			this.connected = !!event.connected;
			this.error = event.error ?? '';
			if (event.connected) this.enabled = true;
			return;
		}
		if (event.type === 'tag' && !this.busy && event.uid) {
			if (event.uid === this.handled) return;
			// Already on screen: re-setting it would restart the owner lookup for a
			// tag the user is currently looking at.
			if (this.tag?.uid === event.uid) return;
			this.tag = event;
		}
	}

	/**
	 * Take the reader for a dialog. Returns the matching release, so a caller can
	 * hand it straight to an effect teardown and not have to pair the calls.
	 */
	claim(): () => void {
		this.claims += 1;
		let released = false;
		return () => {
			if (released) return;
			released = true;
			this.claims = Math.max(0, this.claims - 1);
		};
	}

	dismissTag() {
		this.handled = this.tag?.uid ?? this.handled;
		this.tag = null;
	}

	/**
	 * Treat a tag as dealt with without it having been shown — used after writing
	 * or erasing one, which otherwise leaves it sitting on the reader waiting to
	 * be announced as a discovery.
	 */
	suppress(uid: string) {
		if (uid) this.handled = uid;
	}

	formatLabel(key: string): string {
		return this.formats.find((f) => f.key === key)?.label ?? key;
	}
}

export const nfc = new NfcState();
