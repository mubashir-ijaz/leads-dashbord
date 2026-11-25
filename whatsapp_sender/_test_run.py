import builtins

_answers = ["5", "1", "5"]


def fake_input(prompt=""):
    val = _answers.pop(0)
    print(f"{prompt}{val}")
    return val


builtins.input = fake_input

import whatsapp_dm

whatsapp_dm.main()
