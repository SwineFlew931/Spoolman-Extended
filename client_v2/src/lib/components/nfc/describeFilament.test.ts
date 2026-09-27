import { describe, expect, it } from 'vitest';
import { describeFilament, filamentVariant } from './describeFilament';
import type { Extra, Filament, Vendor } from '$lib/types';

function filament(over: Partial<Filament> = {}): Filament {
	return {
		id: '12',
		vendorId: '12',
		name: 'White',
		material: 'PLA',
		colors: ['FFFFFF'],
		diameter: 1.75,
		density: 1.24,
		nozzleTemp: 220,
		bedTemp: 60,
		weight: 1000,
		price: 15,
		comment: '',
		registeredLabel: 'Aug 4',
		tags: [],
		extra: {} as Extra,
		...over
	};
}

const elegoo = { id: '12', name: 'Elegoo' } as Vendor;

describe('filamentVariant', () => {
	it('prefers the variant', () => {
		const f = filament({ extra: { variant: '"Matte"', subtype: '"Basic"' } as Extra });
		expect(filamentVariant(f)).toBe('Matte');
	});

	it('falls back to the subtype', () => {
		expect(filamentVariant(filament({ extra: { subtype: '"Silk"' } as Extra }))).toBe('Silk');
	});

	it('is empty when neither is set, which is the common case', () => {
		expect(filamentVariant(filament())).toBe('');
	});

	it('ignores an empty stored value rather than showing a gap', () => {
		expect(filamentVariant(filament({ extra: { variant: '""' } as Extra }))).toBe('');
	});

	it('reads a value that was stored unencoded', () => {
		expect(filamentVariant(filament({ extra: { variant: 'Matte' } as Extra }))).toBe('Matte');
	});

	it('ignores a field holding something that is not text', () => {
		expect(filamentVariant(filament({ extra: { variant: '42' } as Extra }))).toBe('');
	});
});

describe('describeFilament', () => {
	it('spells out brand, material, variant and colour', () => {
		const f = filament({ extra: { variant: '"Basic"' } as Extra });
		expect(describeFilament(f, elegoo)).toBe('Elegoo / PLA / Basic / White');
	});

	it('drops the variant when there is none', () => {
		expect(describeFilament(filament(), elegoo)).toBe('Elegoo / PLA / White');
	});

	it('drops the vendor when it is unknown', () => {
		expect(describeFilament(filament(), undefined)).toBe('PLA / White');
	});

	it('survives a filament with nothing to say', () => {
		const bare = filament({ name: '', material: '', vendorId: '' });
		expect(describeFilament(bare, undefined)).toBe('#12');
	});

	it('trims stray whitespace instead of showing a double separator', () => {
		const f = filament({ name: '  White  ', material: ' PLA ' });
		expect(describeFilament(f, elegoo)).toBe('Elegoo / PLA / White');
	});
});
