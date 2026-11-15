class Registry:
    plugins = []

    @classmethod
    def add(cls, name):
        cls.plugins.append(name)
        return len(cls.plugins)


def register(name):
    return Registry.add(name)


def registered():
    return list(Registry.plugins)
