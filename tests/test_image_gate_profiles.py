from ai_story.image_gate_profiles import neutral_identity_portrait_gates


def test_neutral_identity_portrait_gates_are_mandatory_and_localize_anatomy() -> None:
    gates = neutral_identity_portrait_gates()

    assert [gate["probe_id"] for gate in gates] == [
        "localized_face_neck_anatomy_gate",
        "single_subject_gate",
        "head_shoulders_portrait_framing_gate",
    ]
    assert all(gate["required"] for gate in gates)
    assert gates[0]["crop_box_normalized"] == [0.24, 0.0, 0.76, 0.43]
    assert [gate["minimum_expected_score"] for gate in gates] == [0.24, 0.20, 0.235]
    assert [gate["minimum_contrast_margin"] for gate in gates] == [0.0, -0.005, 0.0]
    assert all(gate["forbidden"] for gate in gates)
