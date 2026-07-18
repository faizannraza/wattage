import pytest

from wattage.convergence.embed import HashEmbedder, NullEmbedder, build_embedder


def test_hash_embedder_identical_texts_score_one() -> None:
    embedder = HashEmbedder()
    assert embedder.similarity("the quick brown fox", "the quick brown fox") == 1.0


def test_hash_embedder_ranks_similar_above_unrelated() -> None:
    embedder = HashEmbedder()
    similar = embedder.similarity("the quick brown fox jumps", "the quick brown fox leaps")
    unrelated = embedder.similarity("the quick brown fox", "quantum entanglement physics")
    assert similar > unrelated


def test_hash_embedder_empty_text_is_neutral() -> None:
    embedder = HashEmbedder()
    assert embedder.similarity("", "anything") == 0.5
    assert embedder.similarity("anything", "") == 0.5


def test_novelty_vs_identical_prior_is_zero() -> None:
    embedder = HashEmbedder()
    assert embedder.novelty("repeat me", ["repeat me"]) == 0.0


def test_novelty_with_no_priors_is_neutral() -> None:
    embedder = HashEmbedder()
    assert embedder.novelty("anything", []) == 0.5
    assert embedder.novelty("anything", ["", ""]) == 0.5  # only empty priors -> same as none


def test_novelty_with_no_text_is_neutral() -> None:
    embedder = HashEmbedder()
    assert embedder.novelty("", ["prior"]) == 0.5


def test_null_embedder_always_neutral() -> None:
    embedder = NullEmbedder()
    assert embedder.similarity("a", "b") == 0.5
    assert embedder.novelty("a", ["b", "c"]) == 0.5


def test_build_embedder_off_returns_null() -> None:
    embedder = build_embedder("off")
    assert isinstance(embedder, NullEmbedder)


def test_build_embedder_local_works_regardless_of_optional_extra() -> None:
    # Whether or not wattage[embeddings] happens to be installed in this
    # environment, "local" must return a working embedder.
    embedder = build_embedder("local")
    assert 0.0 <= embedder.similarity("hello world", "hello there world") <= 1.0


def test_build_embedder_api_is_a_documented_not_yet() -> None:
    with pytest.raises(NotImplementedError):
        build_embedder("api")


def test_build_embedder_unknown_mode_raises() -> None:
    with pytest.raises(ValueError, match="Unknown embed mode"):
        build_embedder("nonsense")
