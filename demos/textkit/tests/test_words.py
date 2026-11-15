from textkit.words import initials, is_palindrome, title_case, word_count


def test_word_count():
    assert word_count("the quick brown fox") == 4


def test_word_count_empty():
    assert word_count("") == 0


def test_title_case_keeps_small_words_lower():
    assert title_case("the lord of the rings") == "The Lord of the Rings"


def test_palindrome_ignores_punctuation():
    assert is_palindrome("A man, a plan, a canal: Panama")


def test_initials():
    assert initials("ada lovelace") == "AL"
