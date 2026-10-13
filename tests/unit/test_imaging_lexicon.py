import io

import numpy as np
from PIL import Image
from pytest import approx

from yomiplay.assist.imaging import box_to_screen, crop_box, png_bytes, prepare_for_model
from yomiplay.assist.lexicon import FugashiTokenizer, content_words


def synthetic(w=320, h=240):
    rgba = np.zeros((h, w, 4), np.uint8); rgba[..., 3] = 255
    rgba[int(h * 0.7):, :, 2] = 255  # blue "dialogue box" area
    return rgba


def test_png_round_trip():
    img = Image.open(io.BytesIO(png_bytes(synthetic())))
    assert img.size == (320, 240)


def test_prepare_crops_and_upscales():
    img = Image.open(io.BytesIO(prepare_for_model(synthetic(), [(0.0, 0.7, 1.0, 0.3)], scale=3)))
    assert img.size == (960, 216)
    assert img.getpixel((10, 10))[2] == 255


def test_prepare_whole_frame_when_no_rect():
    img = Image.open(io.BytesIO(prepare_for_model(synthetic(350, 240), [], scale=2)))
    assert img.size == (700, 480)


def test_tokenizer_collapses_conjugations_and_drops_particles():
    tok = FugashiTokenizer()
    words = content_words(tok.tokenize("見つけた本を見つけて、見つける。"))
    lemmas = [w.lemma for w in words]
    assert lemmas == ["見つける", "本"]
    assert words[0].reading == "みつける" and words[0].pos == "動詞"


def test_tokenizer_maps_kana_writing_to_kanji_dictionary_form():
    words = content_words(FugashiTokenizer().tokenize("あしたは みずうみで あそぼう"))
    assert [(w.lemma, w.reading) for w in words] == [("明日", "あした"), ("湖", "みずうみ"), ("遊ぶ", "あそぶ")]


def test_tokenizer_keeps_loanwords_as_written():
    words = content_words(FugashiTokenizer().tokenize("ボンバーと あそぶ"))
    assert words[0].lemma == "ボンバー" and words[0].reading == "ぼんばー"


def test_tokenizer_handles_empty_and_latin():
    tok = FugashiTokenizer()
    assert content_words(tok.tokenize("")) == []
    assert [w.lemma for w in content_words(tok.tokenize("OK"))] == ["OK"]


def test_crop_box_whole_screen_without_rects():
    assert crop_box([], 320, 240) == (0, 0, 320, 240)


def test_crop_box_union_of_rects_clamped():
    assert crop_box([(0.0, 0.7, 1.0, 0.3)], 320, 240) == (0, 168, 320, 240)
    assert crop_box([(-0.1, 0.5, 0.5, 0.6)], 320, 240) == (0, 120, 128, 240)


def test_crop_box_empty_union_means_whole_screen():
    assert crop_box([(0.5, 0.5, 0.0, 0.0)], 320, 240) == (0, 0, 320, 240)


def test_box_to_screen_without_crop_is_a_scale():
    assert box_to_screen([100, 500, 250, 100], [], 320, 240) == approx([0.1, 0.5, 0.25, 0.1], abs=1e-3)


def test_box_to_screen_maps_through_the_crop():
    # crop is the bottom 30 % of the screen; the model box covers the left half, middle third of it
    out = box_to_screen([0, 333, 500, 333], [(0.0, 0.7, 1.0, 0.3)], 320, 240)
    assert out == approx([0.0, 0.8, 0.5, 0.1], abs=1e-3)


def test_box_to_screen_clamps_to_the_crop():
    out = box_to_screen([900, 900, 300, 300], [], 320, 240)
    assert out == approx([0.9, 0.9, 0.1, 0.1], abs=1e-3)


def test_box_to_screen_rejects_bad_boxes():
    for bad in (None, [1, 2, 3], [1, 2, 3, "4"], [True, 0, 10, 10], [0, 0, 0, 50], [1200, 0, 50, 50], "0,0,1,1", [float("nan"), 0, 10, 10], [0, 0, float("inf"), 10]):
        assert box_to_screen(bad, [], 320, 240) is None, bad


def test_box_to_screen_returns_none_for_zero_area_box_with_crop():
    # crop is the bottom 30% of the screen; box has zero width
    out = box_to_screen([100, 100, 0, 100], [(0.0, 0.7, 1.0, 0.3)], 320, 240)
    assert out is None
