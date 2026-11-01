from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
JS = (ROOT / "catalog/view/javascript/flowpages-alchemy.js").read_text(
    encoding="utf-8"
)
CSS = (
    ROOT / "catalog/view/theme/flowpages/stylesheet/flowpages.css"
).read_text(encoding="utf-8")
ALCHEMY_TEMPLATE = (
    ROOT / "catalog/view/theme/flowpages/template/product/alchemy.twig"
).read_text(encoding="utf-8")
HEADER_TEMPLATE = (
    ROOT / "catalog/view/theme/flowpages/template/common/header.twig"
).read_text(encoding="utf-8")
ALCHEMY_CONTROLLER = (
    ROOT / "catalog/controller/product/alchemy.php"
).read_text(encoding="utf-8")
ALCHEMY_MODEL = (
    ROOT / "catalog/model/product/alchemy.php"
).read_text(encoding="utf-8")
ALCHEMY_REPORT = (
    ROOT / "tools/book_catalog/report_alchemy_quality.php"
).read_text(encoding="utf-8")
ALCHEMY_INSTALLER = (
    ROOT / "tools/book_catalog/install_alchemy_storage.php"
).read_text(encoding="utf-8")


class AlchemyFrontendContractTest(unittest.TestCase):
    def test_full_and_residual_queries_are_sent_separately(self) -> None:
        self.assertIn("residualQuery: ''", JS)
        self.assertIn("analysis.residual_query", JS)
        self.assertIn("residual_query: state.residualQuery", JS)
        self.assertIn("'residual_query'", ALCHEMY_CONTROLLER)

    def test_safe_empty_and_partial_states_are_explained(self) -> None:
        self.assertIn("data-no-results-filters", ALCHEMY_TEMPLATE)
        self.assertIn("data-partial-results", ALCHEMY_TEMPLATE)
        self.assertIn("payload.state === 'no_candidates'", JS)
        self.assertIn("payload.state === 'partial'", JS)
        self.assertIn("hasMeaningfulText", JS)

    def test_reduced_motion_has_immediate_non_animated_path(self) -> None:
        self.assertIn("@media (prefers-reduced-motion: reduce)", CSS)
        self.assertIn("animation: none !important", CSS)
        self.assertIn("transition: none !important", CSS)
        self.assertIn("function reducedMotion()", JS)
        self.assertIn("if (reducedMotion()) { return Promise.resolve(); }", JS)
        self.assertIn("if (reducedMotion() || !card.animate)", JS)

    def test_ritual_overlay_does_not_animate_layout_properties(self) -> None:
        ritual_rule = CSS.split(".fp-alchemy-ritual {", 1)[1].split("}", 1)[0]
        self.assertIn("position: absolute", ritual_rule)
        self.assertIn("transition: opacity .32s ease, transform .32s ease", ritual_rule)
        for property_name in ("max-height", "margin .", "padding .", "border-width"):
            self.assertNotIn(property_name, ritual_rule)
        self.assertIn('id="fp-alchemy-output"', ALCHEMY_TEMPLATE)

    def test_wishlist_header_exposes_opencart_update_target(self) -> None:
        self.assertIn('id="wishlist-total"', HEADER_TEMPLATE)
        self.assertIn("<span>{{ text_wishlist }}</span>", HEADER_TEMPLATE)

    def test_catalog_style_cards_have_one_matching_characteristics_field(self) -> None:
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr))", CSS)
        self.assertIn("function matchingCharacteristics(product)", JS)
        self.assertIn("product.matched || []", JS)
        self.assertIn("product.reasons || []", JS)
        self.assertNotIn("product.unmet || []", JS)
        self.assertNotIn("function appendTags(", JS)

    def test_feedback_controls_and_backend_are_removed(self) -> None:
        for source in (JS, ALCHEMY_TEMPLATE, ALCHEMY_CONTROLLER, ALCHEMY_MODEL, ALCHEMY_REPORT):
            self.assertNotIn("feedback_fit", source)
            self.assertNotIn("feedback_unfit", source)
        self.assertNotIn("replaceFeedbackEvent", ALCHEMY_MODEL)

    def test_saved_recipes_ui_and_backend_are_removed(self) -> None:
        self.assertNotIn("data-save-url", ALCHEMY_TEMPLATE)
        self.assertNotIn("data-recipes-url", ALCHEMY_TEMPLATE)
        self.assertNotIn("fp-alchemy-saved", ALCHEMY_TEMPLATE)
        self.assertNotIn("saveCurrentRecipe", JS)
        self.assertNotIn("loadSavedRecipes", JS)
        self.assertNotIn("public function save()", ALCHEMY_CONTROLLER)
        self.assertNotIn("public function recipes()", ALCHEMY_CONTROLLER)
        self.assertNotIn("saveRecipe(", ALCHEMY_MODEL)
        self.assertNotIn("getRecipes(", ALCHEMY_MODEL)
        self.assertNotIn("recipe_loaded", ALCHEMY_CONTROLLER)
        self.assertNotIn("recipe_saved", ALCHEMY_REPORT)
        self.assertNotIn("alchemy_recipe", ALCHEMY_INSTALLER)

    def test_purchase_actions_use_the_catalogue_corner_radius(self) -> None:
        alchemy_actions = CSS.split(".fp-alchemy-book__actions button {", 1)[1].split("}", 1)[0]
        catalogue_actions = CSS.split(".fp-catalog-card__actions button {", 1)[1].split("}", 1)[0]
        self.assertIn("border-radius: 10px", alchemy_actions)
        self.assertIn("border-radius: 10px", catalogue_actions)

    def test_removed_feedback_does_not_leave_reserved_card_height(self) -> None:
        card_rule = CSS.split(".fp-alchemy-book {", 1)[1].split("}", 1)[0]
        self.assertIn("min-height: 0", card_rule)
        self.assertNotIn("min-height: 606px", card_rule)

    def test_matching_characteristics_have_no_bottom_rule(self) -> None:
        evidence_rule = CSS.split(".fp-alchemy-book__evidence {", 1)[1].split("}", 1)[0]
        self.assertIn("border-top:", evidence_rule)
        self.assertNotIn("border-bottom:", evidence_rule)

    def test_recipe_finishing_controls_are_visually_quiet_and_aligned(self) -> None:
        surprise_rule = CSS.split(".fp-alchemy-surprise {", 1)[1].split("}", 1)[0]
        self.assertIn("border: 1px solid var(--fp-line)", surprise_rule)
        self.assertIn("background: #f7f4ed", surprise_rule)
        self.assertNotIn("background: var(--fp-walnut)", surprise_rule)
        self.assertNotIn("fp-alchemy-mixbar__formula", ALCHEMY_TEMPLATE)
        self.assertIn("justify-content: flex-end", CSS)
        self.assertIn(".fp-alchemy-age-field select { margin-top: 15px; }", CSS)
        surprise_heading = CSS.split(".fp-alchemy-surprise h3 {", 1)[1].split("}", 1)[0]
        self.assertIn("font-size: 24px", surprise_heading)
        self.assertIn("color: var(--fp-ink)", surprise_heading)
        surprise_output = CSS.split(".fp-alchemy-surprise h3 output {", 1)[1].split("}", 1)[0]
        self.assertIn("color: inherit", surprise_output)
        self.assertIn("font: inherit", surprise_output)

    def test_anchor_hint_and_range_fill_have_explicit_ui_contracts(self) -> None:
        self.assertIn('class="fp-alchemy-wide-card__help"', ALCHEMY_TEMPLATE)
        self.assertIn('data-anchor-aspects-placeholder=', ALCHEMY_TEMPLATE)
        anchor_help = CSS.split(".fp-alchemy-wide-card__help {", 1)[1].split("}", 1)[0]
        self.assertIn("font-size: 13px", anchor_help)
        self.assertIn("color: #67635c", anchor_help)
        self.assertIn("function updateAnchorRangeFill(input)", JS)
        self.assertIn("--fp-range-progress", JS)
        self.assertIn("--fp-range-progress", CSS)
        self.assertIn('input[type="range"]::-webkit-slider-runnable-track', CSS)

    def test_recipe_markers_and_strict_exclusion_controls_match_their_meaning(self) -> None:
        self.assertIn('fp-alchemy-marker--positive', ALCHEMY_TEMPLATE)
        self.assertIn('fa fa-check', ALCHEMY_TEMPLATE)
        self.assertIn('fp-alchemy-marker--negative', ALCHEMY_TEMPLATE)
        self.assertIn('fa fa-times', ALCHEMY_TEMPLATE)
        self.assertNotIn('fp-alchemy-dot', ALCHEMY_TEMPLATE)
        self.assertIn("var strictMode = negative && item.mode === 'exclude'", JS)
        self.assertIn("controls.appendChild(weightWrap)", JS)
        self.assertIn("fp-alchemy-ingredient__controls--strict", JS)


if __name__ == "__main__":
    unittest.main()
