<script lang="ts">
	// The NFC/RFID tags linked to a spool or filament, listed in its inspector.
	//
	// A tag is identified by its hardware UID and nothing else, so there is very
	// little to show: the UID, what kind of tag it is when the reader said, and
	// when it was linked. What matters is that the UID shown is the server's
	// canonical spelling — the same physical tag reads as `04:a2:b3:c4` on one
	// reader and `04-A2-B3-C4` on another, and showing whichever spelling happened
	// to be typed would make one tag look like several.
	//
	// Adding is a quiet section action rather than another button in the inspector
	// header: that header already carries the primary actions, and linking a tag is
	// not one of the things you do every day.
	import SectionLabel from './SectionLabel.svelte';
	import AddTagModal from './AddTagModal.svelte';
	import NfcWriteDialog from './nfc/NfcWriteDialog.svelte';
	import ConfirmDialog from './ConfirmDialog.svelte';
	import Plus from '@lucide/svelte/icons/plus';
	import Nfc from '@lucide/svelte/icons/nfc';
	import PenLine from '@lucide/svelte/icons/pen-line';
	import X from '@lucide/svelte/icons/x';
	import type { Spool, Tag } from '$lib/types';
	import { unlinkTag, type TagKind } from '$lib/api/tags';
	import { nfcWriter } from '$lib/stores/nfcWriter.svelte';
	import { toasts } from '$lib/stores/toasts.svelte';
	import { formatShortDate } from '$lib/utils/datetime';
	import * as m from '$lib/paraglide/messages';

	interface Props {
		/** What the tags identify, and so where links and unlinks go. */
		kind: TagKind;
		id: number | string;
		tags: Tag[];
		/**
		 * The spool itself, when this is a spool's section. Only needed to write a
		 * tag -- the writer service has no database and is sent the whole spool --
		 * so it is optional, and without it only linking is offered.
		 */
		spool?: Spool | null;
	}
	let { kind, id, tags, spool = null }: Props = $props();

	let addOpen = $state(false);
	let writeOpen = $state(false);

	// Writing needs a writer service and a spool to write. Filaments can hold
	// tags, but there is no filament payload format, so they link only.
	const canWrite = $derived(kind === 'spool' && !!spool && nfcWriter.usable);
	let pending = $state<Tag | null>(null);
	let unlinking = $state(false);

	async function confirmUnlink() {
		const tag = pending;
		if (!tag) return;
		unlinking = true;
		try {
			await unlinkTag({ kind, id }, tag.uid);
			// No local edit: unlinking emits the holder's ordinary `updated` event, and
			// the list below re-renders from the cache when it arrives.
			toasts.success(m['tags.unlinked']());
			pending = null;
		} catch {
			toasts.error(m['tags.unlinkFailed']());
		} finally {
			unlinking = false;
		}
	}

	function unlinkBody(uid: string): string {
		return kind === 'spool' ? m['tags.unlinkBody']({ uid }) : m['tags.unlinkBodyFilament']({ uid });
	}
</script>

<SectionLabel>
	{m['tags.section']()}
	{#snippet right()}
		{#if canWrite}
			<button class="link" onclick={() => (writeOpen = true)}>
				<PenLine size={13} />
				{m['nfc.writeAction']()}
			</button>
		{/if}
		<button class="link" onclick={() => (addOpen = true)}>
			<Plus size={13} />
			{m['tags.add']()}
		</button>
	{/snippet}
</SectionLabel>

{#if tags.length}
	<ul class="tags">
		{#each tags as tag (tag.uid)}
			<li class="tag">
				<Nfc size={14} class="ico" />
				<span class="uid mono">{tag.uid}</span>
				{#if tag.format}<span class="fmt">{tag.format}</span>{/if}
				<span class="added">{m['tags.addedOn']({ date: formatShortDate(tag.added) })}</span>
				<button
					class="unlink"
					onclick={() => (pending = tag)}
					title={m['tags.unlink']()}
					aria-label={m['tags.unlink']()}
				>
					<X size={14} />
				</button>
			</li>
		{/each}
	</ul>
{:else}
	<div class="none">{m['tags.none']()}</div>
{/if}

<AddTagModal open={addOpen} {kind} {id} onclose={() => (addOpen = false)} />

{#if canWrite}
	<NfcWriteDialog open={writeOpen} {spool} {kind} {id} onclose={() => (writeOpen = false)} />
{/if}

<ConfirmDialog
	open={pending !== null}
	busy={unlinking}
	title={m['tags.unlinkTitle']()}
	lines={pending ? [unlinkBody(pending.uid)] : []}
	confirmLabel={unlinking ? m['tags.unlinking']() : m['tags.unlink']()}
	onconfirm={confirmUnlink}
	onclose={() => (pending = null)}
/>

<style>
	.link {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: 11px;
		color: var(--accent-link);
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
	}
	.link:hover {
		text-decoration: underline;
	}
	.tags {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.tag {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 12px;
		padding: 5px 8px;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
	}
	.tag :global(.ico) {
		color: var(--text-dim);
		flex: none;
	}
	.uid {
		font-weight: 600;
		/* The UID is the whole identity of the tag, so it gets the room; everything
		   after it is context and may be dropped on a narrow inspector. */
		overflow-wrap: anywhere;
	}
	.fmt {
		font-size: 10.5px;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-muted);
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
		padding: 1px 5px;
		flex: none;
	}
	.added {
		margin-left: auto;
		color: var(--text-dim);
		font-size: 11px;
		white-space: nowrap;
	}
	.unlink {
		flex: none;
		display: inline-flex;
		color: var(--text-dim);
		background: none;
		border: none;
		padding: 2px;
		cursor: pointer;
	}
	.unlink:hover {
		color: var(--danger);
	}
	.none {
		font-size: 12px;
		color: var(--text-dim);
	}
</style>
