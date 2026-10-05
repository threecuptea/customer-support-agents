// GENERATED FILE — do not hand-edit.
// Source of truth: backend/models/model.py (ExchangeReturnReason enum).
// Regenerate with: uv run python -m scripts.export_exchange_return_reasons (from backend/).
//
// `value` is submitted as `reason_option` in ExchangeOrReturnInput — it must
// match the backend enum's value exactly, which is why this file is generated
// rather than hand-maintained.

export interface ExchangeReturnReasonOption {
  key: string;
  value: string;
}

export const EXCHANGE_RETURN_REASONS: ExchangeReturnReasonOption[] = [
  {
    "key": "WRONG_SIZE_OR_FIT",
    "value": "Size is too small or too large, different from size chart or just does not fit well"
  },
  {
    "key": "NOT_MATCH_DESCRIPTION_OR_PHOTO",
    "value": "Discrepancies in color, material quality, or features create a gap between customer expectations and reality"
  },
  {
    "key": "DAMAGED_DEFECTIVE_OR_MISSING_PARTS",
    "value": "Items arriving broken, defective or missing parts and make it non-funcional and a return or replacement mandatory"
  },
  {
    "key": "CHANGED_MIND_OR_IMPULSE_BUY",
    "value": "Buyer's remorse to buy it or just don't want it any more"
  },
  {
    "key": "LATE_DELIVERY_NO_LONGER_NEEDED",
    "value": "Products arriving past the needed date of a holiday/ event/ project or the event got canceled and no longer needed any more"
  },
  {
    "key": "WRONG_ITEM_SHIPPED",
    "value": "Possibly pick-and-pack or labeling mistakes in the warehouse"
  },
  {
    "key": "BETTER_PRICE_FOUND",
    "value": "Find a better price in a competitor's site"
  },
  {
    "key": "DIFFICULT_TO_ASSEMBLY",
    "value": "The item is overly complex or the instructions are incomprehensive"
  },
  {
    "key": "DIFFERENT_COLOR_OR_STYLE",
    "value": "Want a different color or style"
  },
  {
    "key": "OTHERS",
    "value": "None of the above"
  }
];
