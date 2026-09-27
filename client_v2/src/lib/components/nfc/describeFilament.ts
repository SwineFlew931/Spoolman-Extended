/**
 * Spell out what a tag identifies: brand, material, variant and colour.
 *
 * The tag-found dialog is usually answering "what *is* this roll?", asked by
 * someone holding it, so a name and a number is thinner than it needs to be --
 * `filamentLabel` gives "Elegoo White", which does not say PLA and does not say
 * Matte. This assembles the fuller form instead:
 *
 *     Elegoo / PLA / Basic / White
 *
 * `filamentLabel` is left alone because the rest of the library uses it, in
 * table cells and pickers where the long form would not fit.
 *
 * Every part is optional and empties are dropped, which matters: most filaments
 * here carry neither variant nor subtype, so the common result is the
 * three-part "Elegoo / PLA / White".
 */
import type { Extra, Filament, Vendor } from '$lib/types';

/**
 * A custom text field's value, or '' if it is unset or holds anything else.
 *
 * Extra values are stored JSON-encoded, so a text field reads as '"Basic"'
 * rather than 'Basic', and a field of another type can be a number or object.
 */
function extraText(extra: Extra | undefined, key: string): string {
	const raw = extra?.[key];
	if (raw === undefined) return '';
	try {
		const parsed: unknown = JSON.parse(raw);
		return typeof parsed === 'string' ? parsed.trim() : '';
	} catch {
		// Older rows were written unencoded; the raw string is the value.
		return raw.trim();
	}
}

/**
 * The variant, falling back to the subtype.
 *
 * Both fields exist and mean much the same thing, filled in at different times;
 * where a filament has both they usually agree, so showing one is enough and
 * showing both would read as a stutter.
 */
export function filamentVariant(filament: Filament): string {
	return extraText(filament.extra, 'variant') || extraText(filament.extra, 'subtype');
}

export function describeFilament(filament: Filament, vendor: Vendor | undefined): string {
	const parts = [vendor?.name, filament.material, filamentVariant(filament), filament.name]
		.map((s) => s?.trim())
		.filter(Boolean);
	return parts.length ? parts.join(' / ') : `#${filament.id}`;
}
