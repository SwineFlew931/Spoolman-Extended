<script lang="ts">
	// Writing one spool to one tag, and linking the tag it landed on.
	//
	// Structured like ConfirmDialog (window-level Escape, backdrop as a sibling
	// button, role="dialog" + tabindex="-1") so it behaves like every other modal
	// here and stays clean under svelte-check's a11y rules.
	//
	// The write is a single request that stays open while the reader waits for a
	// tag, so "waiting" is literally the request in flight and cancelling aborts
	// it, which is what lets the service disarm the reader.
	//
	// Two services, in a deliberate order. The writer puts bytes on the tag and
	// reports the UID it saw; Spoolman then links that UID, through the same
	// `linkTag` the by-hand flow uses. Writing first matters: a link to a tag that
	// then failed to write is a lie the user cannot see, whereas a written tag that
	// failed to link is visible and re-linkable from the tag list.
	import { untrack } from 'svelte';
	import Button from '../Button.svelte';
	import X from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages';
	import {
		previewTag,
		writeTag,
		NfcWriterError,
		UNREACHABLE,
		WRITER_BASE,
		type OperationResult,
		type TagPreview
	} from '$lib/api/nfcWriter';
	import { linkTag, asTagConflict, KNOWN_FORMATS, type TagKind } from '$lib/api/tags';
	import { nfcWriter } from '$lib/stores/nfcWriter.svelte';
	import { inventory } from '$lib/stores/inventory.svelte';
	import { filamentLabel } from '$lib/utils/library';
	import type { Spool } from '$lib/types';

	interface Props {
		open: boolean;
		/** Sent to the writer whole: the service has no database to look it up in. */
		spool: Spool | null;
		/** Where the UID is linked once written. Filaments can hold tags too. */
		kind: TagKind;
		id: number | string;
		onclose: () => void;
		ondone?: (result: OperationResult) => void;
	}

	let { open, spool, kind, id, onclose, ondone }: Props = $props();

	type Phase = 'idle' | 'waiting' | 'linking' | 'done' | 'error';

	let format = $state('');
	let preview = $state<TagPreview | null>(null);
	let phase = $state<Phase>('idle');
	let result = $state<OperationResult | null>(null);
	let linked = $state(false);
	let linkWarning = $state('');
	let errorText = $state('');
	let controller: AbortController | null = null;

	let dialog = $state<HTMLDivElement | null>(null);
	let opener: HTMLElement | null = null;

	// Named for the heading the same way the rest of the library names a spool, so
	// the dialog agrees with the inspector it was opened from. Resolved from the
	// cache rather than passed down, which keeps TagsSection from having to carry a
	// label it has no other use for.
	const heading = $derived.by(() => {
		if (!spool) return '';
		const filament = inventory.filamentById(spool.filamentId);
		if (!filament) return `#${spool.id}`;
		const vendor = filament.vendorId ? inventory.vendorById(filament.vendorId) : undefined;
		return filamentLabel(filament, vendor);
	});

	const chosen = $derived(nfcWriter.formats.find((f) => f.key === format) ?? null);
	const busy = $derived(phase === 'waiting' || phase === 'linking');
	const canWrite = $derived(!!spool && nfcWriter.usable && !busy && !!format);

	$effect(() => {
		if (open) {
			opener ??= document.activeElement as HTMLElement | null;
			dialog?.focus();
		} else if (opener) {
			opener.focus();
			opener = null;
		}
	});

	// Opening offers the format used last rather than a fixed default. A workshop
	// standardises on one format, so re-choosing it for every spool is the kind of
	// friction that stops a feature being used; and unlike a stale in-memory value,
	// a remembered choice is one the user made on purpose and can see in the field.
	//
	// Everything inside is untracked, and that is load-bearing rather than tidy.
	// This is a reset that should happen when the dialog opens and at no other
	// time, but it reads `nfcWriter.lastFormat` -- which a successful write then
	// sets via rememberFormat(). Tracked, that made writing re-run this reset:
	// `result` was nulled while `await link()` was still in flight, so a write
	// that had genuinely succeeded finished with an empty dialog and no
	// confirmation. Found by writing a real tag; nothing failed, the report
	// just vanished.
	$effect(() => {
		if (!open) return;
		untrack(() => {
			phase = 'idle';
			result = null;
			linked = false;
			linkWarning = '';
			errorText = '';
			format = nfcWriter.lastFormat || nfcWriter.formats[0]?.key || '';
		});
	});

	// Re-render the preview whenever the spool or format changes, so the
	// recommendation always describes what would actually be written.
	$effect(() => {
		const s = spool;
		const key = format;
		if (!open || !s || !key) {
			preview = null;
			return;
		}
		let stale = false;
		previewTag(s.id, key)
			.then((p) => {
				if (!stale) preview = p;
			})
			.catch(() => {
				if (!stale) preview = null;
			});
		return () => {
			stale = true;
		};
	});

	function close() {
		if (busy) cancel();
		onclose();
	}

	function cancel() {
		controller?.abort();
		controller = null;
		phase = 'idle';
	}

	/**
	 * Link the UID just written to. Failures here are reported but do not fail the
	 * write, because the tag really does carry the data — so this sets a warning
	 * rather than moving to the error phase.
	 */
	async function link(uid: string) {
		phase = 'linking';
		// Upstream's `format` is the tag's hardware type and is informational. Our
		// content format is only passed when it is a spelling upstream already
		// knows, rather than inventing vocabulary in a shared field.
		const known = (KNOWN_FORMATS as readonly string[]).includes(format);
		try {
			await linkTag({ kind, id }, uid, known ? format : undefined);
			linked = true;
		} catch (e) {
			const conflict = asTagConflict(e);
			linkWarning = conflict ? m['nfc.linkConflict']({ uid }) : m['nfc.linkFailed']({ uid });
		}
	}

	async function write() {
		if (!spool || !format) return;
		phase = 'waiting';
		errorText = '';
		linkWarning = '';
		result = null;
		linked = false;
		controller = new AbortController();
		try {
			const outcome = await writeTag(spool.id, format, { signal: controller.signal });
			result = outcome;
			if (outcome.ok) {
				nfcWriter.rememberFormat(format);
				if (outcome.uid) await link(outcome.uid);
				phase = 'done';
				ondone?.(outcome);
			} else {
				phase = 'error';
				errorText = outcome.message;
			}
		} catch (e) {
			if (controller?.signal.aborted) return;
			phase = 'error';
			errorText =
				e instanceof NfcWriterError && e.status === UNREACHABLE
					? m['nfc.writerUnreachable']({ url: WRITER_BASE })
					: e instanceof NfcWriterError
						? e.message
						: String(e);
		} finally {
			controller = null;
		}
	}
</script>

<svelte:window
	onkeydown={(e) => {
		if (open && e.key === 'Escape') close();
	}}
/>

{#if open}
	<div class="overlay">
		<button class="backdrop" tabindex="-1" aria-hidden="true" onclick={close}></button>
		<div
			class="dialog"
			role="dialog"
			aria-modal="true"
			aria-labelledby="nfc-write-title"
			tabindex="-1"
			bind:this={dialog}
		>
			<div class="head">
				<span class="title" id="nfc-write-title">
					{m['nfc.writeAction']()}{heading ? ` — ${heading}` : ''}
				</span>
				<button class="x" onclick={close} aria-label={m['buttons.close']()}><X size={16} /></button>
			</div>

			<div class="body">
				{#if !nfcWriter.available}
					<p class="warn">{m['nfc.writerUnreachable']({ url: WRITER_BASE })}</p>
				{:else if !nfcWriter.connected}
					<p class="warn">{nfcWriter.error || m['nfc.reader.offline']()}</p>
				{/if}

				<div class="field">
					<label class="lbl" for="nfc-format">{m['nfc.format.label']()}</label>
					<select id="nfc-format" bind:value={format} disabled={busy}>
						{#each nfcWriter.formats as fmt (fmt.key)}
							<option value={fmt.key}>{fmt.label}</option>
						{/each}
					</select>
				</div>
				{#if chosen}
					<p class="desc">{chosen.description}</p>
				{/if}

				{#if preview}
					{#if preview.writes_tag}
						<p class="size">{m['nfc.payloadSize']({ size: preview.size })}</p>
					{:else}
						<p class="size">{m['nfc.nothingWritten']()}</p>
					{/if}

					{#if preview.notes.length}
						<div class="notes">
							<div class="notes-title">{m['nfc.notesTitle']()}</div>
							{#each preview.notes as note (note)}
								<p>{note}</p>
							{/each}
						</div>
					{/if}

					{#if preview.writes_tag}
						<div class="chips-head">{m['nfc.recommendedTags']()}</div>
						<ul class="chips">
							{#each preview.recommended as chip (chip.name)}
								<li class:no={!chip.fits}>
									<span class="chip-name">{chip.name}</span>
									<span class="chip-note">
										{#if chip.fits}
											{m['nfc.chipFits']({ headroom: chip.headroom })}
										{:else}
											{m['nfc.chipTooSmall']({ over: -chip.headroom })}
										{/if}
									</span>
								</li>
							{/each}
						</ul>
						<p class="hint">{m['nfc.recommendedHint']()}</p>
					{/if}
				{/if}

				{#if phase === 'waiting'}
					<div class="status waiting">
						<div class="status-title">{m['nfc.armed']()}</div>
						<p>{m['nfc.armedHint']()}</p>
					</div>
				{:else if phase === 'linking'}
					<div class="status waiting">
						<div class="status-title">{m['nfc.linking']()}</div>
					</div>
				{:else if phase === 'done' && result}
					<div class="status ok">
						<div class="status-title">
							{#if result.written_bytes}
								{m['nfc.written']({ bytes: result.written_bytes })}
							{:else}
								{m['nfc.erase.done']()}
							{/if}
						</div>
						<p class="mono">{m['nfc.uid']()}: {result.uid}</p>
						{#if linked}<p>{m['nfc.bound']()}</p>{/if}
						{#if linkWarning}<p class="warn">{linkWarning}</p>{/if}
					</div>
				{:else if phase === 'error'}
					<div class="status bad">
						<div class="status-title">{errorText}</div>
					</div>
				{/if}
			</div>

			<div class="foot">
				{#if busy}
					<Button variant="outline" onclick={cancel}>{m['nfc.cancel']()}</Button>
				{:else if phase === 'done'}
					<Button onclick={close}>{m['buttons.close']()}</Button>
				{:else}
					<Button variant="outline" onclick={close}>{m['buttons.cancel']()}</Button>
					<Button disabled={!canWrite} onclick={write}>
						{phase === 'error' ? m['nfc.retry']() : m['nfc.writeAction']()}
					</Button>
				{/if}
			</div>
		</div>
	</div>
{/if}

<style>
	.overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.6);
		z-index: 60;
		display: flex;
		align-items: flex-start;
		justify-content: center;
		padding: 10vh 16px 16px;
	}
	.backdrop {
		position: fixed;
		inset: 0;
		border: none;
		margin: 0;
		padding: 0;
		background: transparent;
		cursor: default;
	}
	.dialog {
		position: relative;
		z-index: 1;
		width: 460px;
		max-width: 100%;
		max-height: 80vh;
		display: flex;
		flex-direction: column;
		background: var(--bg);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-xl);
		box-shadow: 0 20px 60px rgba(0, 0, 0, 0.6);
		overflow: hidden;
	}
	.head {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 16px 20px 0;
	}
	.title {
		font-weight: 700;
		font-size: 15px;
	}
	.x {
		margin-left: auto;
		color: var(--text-dim);
		cursor: pointer;
		padding: 4px 8px;
		background: none;
		border: none;
		display: inline-flex;
	}
	.x:hover {
		color: var(--text);
	}
	.body {
		padding: 12px 20px 4px;
		font-size: 13px;
		line-height: 1.5;
		color: var(--text-2);
		overflow-y: auto;
	}
	.body p {
		margin: 0 0 8px;
	}
	.field {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-bottom: 6px;
	}
	.lbl {
		flex: 1;
		font-size: 13px;
		color: var(--text);
	}
	select {
		min-width: 200px;
		font: inherit;
		padding: 5px 8px;
		color: var(--text);
		background: var(--bg-2, var(--bg));
		border: 1px solid var(--border-strong);
		border-radius: var(--radius);
	}
	.desc {
		font-size: 11.5px;
		color: var(--text-dim);
	}
	.size {
		font-size: 12px;
		color: var(--text-dim);
	}
	.warn {
		color: var(--danger, #e5484d);
	}
	.notes {
		border-left: 2px solid var(--border-strong);
		padding: 2px 0 2px 10px;
		margin: 0 0 10px;
	}
	.notes-title {
		font-weight: 600;
		color: var(--text);
		margin-bottom: 4px;
	}
	.chips-head {
		font-weight: 600;
		color: var(--text);
		margin: 10px 0 6px;
	}
	.chips {
		list-style: none;
		margin: 0 0 6px;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 3px;
	}
	.chips li {
		display: flex;
		gap: 8px;
		align-items: baseline;
	}
	.chips li.no {
		color: var(--text-dim);
		text-decoration-line: line-through;
		text-decoration-color: var(--border-strong);
	}
	.chip-name {
		font-weight: 600;
		min-width: 88px;
	}
	.chip-note {
		font-size: 11.5px;
		color: var(--text-dim);
	}
	.hint {
		font-size: 11.5px;
		color: var(--text-dim);
	}
	.status {
		margin-top: 12px;
		padding: 10px 12px;
		border-radius: var(--radius);
		border: 1px solid var(--border-strong);
	}
	.status-title {
		font-weight: 600;
		color: var(--text);
	}
	.status.ok {
		border-color: var(--ok, #30a46c);
	}
	.status.bad {
		border-color: var(--danger, #e5484d);
	}
	.mono {
		font-family: var(--font-mono, monospace);
	}
	.foot {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding: 16px 20px 18px;
		border-top: 1px solid var(--border);
	}
</style>
