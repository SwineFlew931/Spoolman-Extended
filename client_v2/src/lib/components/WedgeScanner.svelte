<script lang="ts">
	// Handheld barcode scanners of the keyboard-wedge kind — Josh's NetumScan
	// NSL5 among them — are not cameras. They type what they read and press
	// Enter, so nothing on screen has to be focused and no permission is asked.
	// QrScannerModal covers the camera case; this covers the other one.
	//
	// A scan is told apart from typing by speed alone: a wedge emits characters
	// milliseconds apart, a person tens to hundreds. Any gap longer than the
	// threshold abandons the buffer, so ordinary typing can never accumulate into
	// something that gets treated as a scan.
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { parseSpoolCode } from '$lib/utils/spoolCode';

	// Wedges typically emit every 5-20 ms; human typing is rarely under 60 ms
	// even at speed, and a burst that pauses is not a scan.
	const MAX_GAP_MS = 50;
	// Shorter than the shortest real code ("WEB+SPOOLMAN:S-1" is 16), so stray
	// fast keystrokes cannot reach the parser.
	const MIN_LENGTH = 8;

	let buffer = '';
	let lastKey = 0;

	/** True when the keystroke belongs to something the user is typing into. */
	function isEditing(target: EventTarget | null): boolean {
		const el = target as HTMLElement | null;
		if (!el) return false;
		const tag = el.tagName;
		return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable === true;
	}

	function onkeydown(event: KeyboardEvent) {
		if (isEditing(event.target)) return;
		// A modifier means a shortcut, not a scan.
		if (event.ctrlKey || event.metaKey || event.altKey) return;

		const now = event.timeStamp;
		if (event.key === 'Enter') {
			const scanned = buffer;
			buffer = '';
			if (scanned.length < MIN_LENGTH) return;
			const ref = parseSpoolCode(scanned);
			if (ref === null) return;
			// Only now is this definitely a scan and not a stray Enter, so this is
			// the first point at which swallowing the key is right.
			event.preventDefault();
			goto(resolve(`/?sel=${ref.kind}:${ref.id}` as '/'));
			return;
		}

		if (event.key.length !== 1) return;
		if (now - lastKey > MAX_GAP_MS) buffer = '';
		buffer += event.key;
		lastKey = now;
	}
</script>

<svelte:window {onkeydown} />
