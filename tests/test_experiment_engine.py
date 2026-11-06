from backend.app.experiment_engine import VariantMetric, decide_two_variant, preflight

def test_preflight_blocks_financial_and_deceptive_changes():
    result = preflight(surface="cta_wording", change_classes=["price", "scarcity_claim"],
                       authority_level=2, approved=True, analytics_ready=True, rollback_ready=True)
    assert not result.allowed
    assert any("price" in failure for failure in result.failures)

def test_level_one_requires_human_approval():
    result = preflight(surface="cta_wording", change_classes=["copy"],
                       authority_level=1, approved=False, analytics_ready=True, rollback_ready=True)
    assert result.failures == ("human_approval_required",)

def test_level_two_rejects_unapproved_surface():
    result = preflight(surface="checkout_layout", change_classes=["copy"],
                       authority_level=2, approved=True, analytics_ready=True, rollback_ready=True)
    assert "surface_not_autonomous" in result.failures

def test_decision_waits_for_sample_and_window():
    variants=[VariantMetric("control", 100, 10, True), VariantMetric("treatment", 100, 20)]
    decision=decide_two_variant(variants=variants, minimum_sample_size=200,
        minimum_practical_effect=.01, confidence_threshold=.95,
        observation_hours=48, minimum_observation_hours=24)
    assert decision.state == "CONTINUE"

def test_decision_can_select_statistically_supported_treatment():
    variants=[VariantMetric("control", 2000, 200, True), VariantMetric("treatment", 2000, 280)]
    decision=decide_two_variant(variants=variants, minimum_sample_size=1000,
        minimum_practical_effect=.01, confidence_threshold=.95,
        observation_hours=72, minimum_observation_hours=24)
    assert decision.state == "WINNER"
    assert decision.winner_variant_id == "treatment"

def test_small_effect_is_inconclusive_even_when_sample_is_large():
    variants=[VariantMetric("control", 100000, 10000, True), VariantMetric("treatment", 100000, 10100)]
    decision=decide_two_variant(variants=variants, minimum_sample_size=1000,
        minimum_practical_effect=.005, confidence_threshold=.95,
        observation_hours=72, minimum_observation_hours=24)
    assert decision.state == "INCONCLUSIVE"
