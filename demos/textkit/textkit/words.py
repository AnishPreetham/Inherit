def word_count(text):
    return len(text.split())


def title_case(text):
    small = {"a", "an", "and", "of", "the", "to"}
    words = text.lower().split()
    return " ".join(w if i and w in small else w.capitalize() for i, w in enumerate(words))


def is_palindrome(text):
    letters = [c.lower() for c in text if c.isalnum()]
    return letters == letters[::-1]


def initials(name):
    return "".join(part[0].upper() for part in name.split() if part)
