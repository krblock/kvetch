Looks at the history of a scan log can help identify reoccurring failures.

```
(venv) $ ./kvetch.py -j "TC/Kvetch-main.linux64" -f
TC/Kvetch-main.linux64 #225 : SUCCESS
-----------------------------------

No known failures were detected


TC/Kvetch-main.linux64 #224 : SUCCESS
-----------------------------------

No known failures were detected


TC/Kvetch-main.linux64 #223 : FAILURE claimed by cdickens
------------------------------------------------------

Build
------
[ERROR] It was the worst of times


TC/Kvetch-main.linux64 #222 : SUCCESS
-----------------------------------

No known failures were detected


TC/Kvetch-main.linux64 #221 : SUCCESS
-----------------------------------

No known failures were detected


TC/Kvetch-main.linux64 #220 : FAILURE claimed by cdickens
------------------------------------------------------

Build
------
[ERROR] It was the worst of times

```
