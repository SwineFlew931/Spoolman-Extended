<script lang="ts">
	// Raised when a tag is tapped and nothing was expecting one.
	//
	// What it offers depends on what the tag turns out to be. A tag that already
	// identifies something can be opened, rewritten or erased; one that identifies
	// nothing can only be erased, because there is no spool in hand to write and
	// guessing at one would be worse than saying so.
	//
	// Unlike the version this is ported from, the lookup is Spoolman's own
	// `findTagHolder`, so a tag on a *filament* is recognised too -- that is a
	// 0.27 feature the integrated fork predated and could not see.
	import Button from '../Button.svelte';
	import ConfirmDialog from '../ConfirmDialog.svelte';
	import X from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { eraseTag, type TagEvent } from '$lib/api/nfcWriter';
	import { findTagHolder, unlinkTag, holderTarget, type TagHolder } from '$lib/api/tags';
	import { nfcWriter } from '$lib/stores/nfcWriter.svelte';
	import { inventory } from '$lib/stores/inventory.svelte';
	import { describeFilament } from './describeFilament';
	import { toasts } from '$lib/stores/toasts.svelte';

	interface Props {
		tag: TagEvent | null;
		onclose: () => void;
	}

	let { tag, onclose }: Props = $props();

	let holder = $state<TagHolder | null>(null);
	let looking = $state(false);
	let confirmErase = $state(false);
	let erasing = $state(false);

	let dialog = $state<HTMLDivElement | null>(null);
	let opener: HTMLElement | null = null;

	const open = $derived(!!tag?.uid);

	// The name to call whatever holds this tag. A spool is named by its filament,
	// not by its id: "#59" is correct and useless, because the point of tapping a
	// tag is usually to find out *what* it is. Spelled out in full here -- brand,
	// material, variant, colour -- since this dialog is read by someone holding
	// the roll and asking exactly that. findTagHolder seeds the cache, so the
	// filament is already here.
	//
	// The id still comes along, in brackets so it reads as a footnote rather than
	// as another slash-separated part of the description.
	const holderName = $derived.by(() => {
		if (!holder) return '';
		if (holder.kind === 'filament') {
			const owner = holder.filament.vendorId ? inventory.vendorById(holder.filament.vendorId) : undefined;
			return describeFilament(holder.filament, owner);
		}
		const spool = holder.spool;
		const filament = inventory.filamentById(spool.filamentId);
		if (!filament) return `#${spool.id}`;
		const vendor = filament.vendorId ? inventory.vendorById(filament.vendorId) : undefined;
		return `${describeFilament(filament, vendor)} (#${spool.id})`;
	});

	$effect(() => {
		if (open) {
			opener ??= document.activeElement as HTMLElement | null;
			dialog?.focus();
		} else if (opener) {
			opener.focus();
			opener = null;
		}
	});

	$effect(() => {
		const uid = tag?.uid;
		if (!uid) {
			holder = null;
			return;
		}
		const controller = new AbortController();
		looking = true;
		findTagHolder(uid, controller.signal)
			.then((found) => {
				if (!controller.signal.aborted) holder = found ?? null;
			})
			.catch(() => {
				// An unreachable server is reported by the dialog saying nothing holds
				// this tag, which is wrong but recoverable; throwing here would leave
				// the dialog stuck with no way out.
				if (!controller.signal.aborted) holder = null;
			})
			.finally(() => {
				if (!controller.signal.aborted) looking = false;
			});
		return () => controller.abort();
	});

	// Only the shapes this can write are named; anything else is reported by its
	// record type rather than guessed at.
	function describe(event: TagEvent): string {
		const type = event.records?.[0]?.type ?? '';
		if (type === 'application/opentag3d') return 'OpenTag3D';
		if (type === 'application/json') return 'OpenSpool';
		if (type === 'urn:nfc:wkt:T') return 'nfc2klipper';
		return type;
	}

	function close() {
		if (!erasing) onclose();
	}

	/**
	 * Blank the tag, and unlink it from whatever held it.
	 *
	 * Two services, and the order matters the opposite way round from writing:
	 * the tag is erased first, and only then unlinked. A link removed from a tag
	 * that then failed to erase would leave a tag carrying data that nothing
	 * claims -- which is exactly the state a duplicate-UID check exists to catch.
	 */
	async function doErase() {
		if (!tag?.uid) return;
		erasing = true;
		const release = nfcWriter.claim();
		const held = holder;
		try {
			const result = await eraseTag();
			if (result.uid) nfcWriter.suppress(result.uid);
			if (!result.ok) {
				toasts.error(result.message);
				return;
			}
			if (held) {
				try {
					await unlinkTag(holderTarget(held), tag.uid);
				} catch {
					toasts.error(m['nfc.erase.unlinkFailed']({ uid: tag.uid }));
					return;
				}
			}
			toasts.success(held ? m['nfc.erase.unbound']() : m['nfc.erase.done']());
		} catch (e) {
			toasts.error(String(e));
		} finally {
			release();
			erasing = false;
			confirmErase = false;
			onclose();
		}
	}

	function goToHolder() {
		if (!holder) return;
		const target = holderTarget(holder);
		onclose();
		goto(resolve(`/?sel=${target.kind}:${target.id}` as '/'));
	}

	function rewrite() {
		if (!holder || holder.kind !== 'spool') return;
		const spool = holder.spool;
		onclose();
		nfcWriter.openWrite(spool);
	}
</script>

<svelte:window
	onkeydown={(e) => {
		if (open && !confirmErase && e.key === 'Escape') close();
	}}
/>

{#if open && tag}
	<div class="overlay">
		<button class="backdrop" tabindex="-1" aria-hidden="true" onclick={close}></button>
		<div
			class="dialog"
			role="dialog"
			aria-modal="true"
			aria-labelledby="nfc-found-title"
			tabindex="-1"
			bind:this={dialog}
		>
			<div class="head">
				<span class="title" id="nfc-found-title">{m['nfc.tagFound.title']()}</span>
				<button class="x" onclick={close} aria-label={m['buttons.close']()}><X size={16} /></button>
			</div>

			<div class="body">
				<p class="mono">{m['nfc.uid']()}: {tag.uid}</p>
				{#if looking}
					<p>{m['nfc.tagFound.checking']()}</p>
				{:else if holder}
					<p>{m['nfc.tagFound.known']({ name: holderName })}</p>
				{:else if tag.blank}
					<p>{m['nfc.tagFound.blank']()}</p>
				{:else}
					<p>{m['nfc.tagFound.unknownData']({ format: describe(tag) })}</p>
				{/if}
			</div>

			<div class="foot">
				<Button variant="outline" disabled={erasing} onclick={() => (confirmErase = true)}>
					{m['nfc.erase.action']()}
				</Button>
				{#if holder?.kind === 'spool'}
					<Button variant="outline" onclick={rewrite}>{m['nfc.overwrite']()}</Button>
				{/if}
				{#if holder}
					<Button onclick={goToHolder}>{m['nfc.goToSpool']()}</Button>
				{/if}
			</div>
		</div>
	</div>
{/if}

<ConfirmDialog
	open={confirmErase}
	title={m['nfc.erase.title']()}
	lines={holder
		? [m['nfc.erase.body'](), m['nfc.erase.unbindBody']({ name: holderName })]
		: [m['nfc.erase.body']()]}
	confirmLabel={m['nfc.erase.confirm']()}
	busy={erasing}
	onconfirm={doErase}
	onclose={() => (confirmErase = false)}
/>

<style>
	.overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.6);
		z-index: 60;
		display: flex;
		align-items: flex-start;
		justify-content: center;
		padding: 12vh 16px 16px;
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
		width: 440px;
		max-width: 100%;
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
	}
	.body p {
		margin: 0 0 8px;
	}
	.mono {
		font-family: var(--font-mono, monospace);
	}
	.foot {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding: 16px 20px 18px;
	}
</style>
