# acnlwa-decomp

### how to setup:

!!!!!!!!!!!! THIS PROJECT REQUIRE ARMCC FOR NINTENDO PATCH 1093 !!!!!!!!!!!!!!!

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# Windows is found automatically in theory, this is mainly for linux:
python tools/compiler.py register <wine prefix>

# Move the .3ds into orig/ folder
cp ../acnlwa.3ds orig/ 

python configure.py
```

open the acnlwa-decomp folder with objdiff after that

```bash
objdiff -p .
```

```bash
# if you are lazy, u can download objdiff and move them automaticaly
python tools/toolchain.py install objdiff

# will show the global location
python tools/toolchain.py which objdiff
```

# Credits:
Somes of the things has been corelated with [LibGarden](https://github.com/Pienco/libgarden) and [usa decomp](https://github.com/RedShyGuy/acnl-decomp)
Special thanks to @EltyDev for [3dsdecomp-toolkit](https://github.com/EltyDev/3dsdecomp-toolkit)
