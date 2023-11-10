# Inferno

* Create a file in the form "old_ids","new_ids",fee
  * Currently only 0 fee is supported correctly
  * If you quote the "old_ids" and "new_ids" cells, you can create them as multi-valued with a comma in between each member value
* Create a venv
  * `python3 -m venv venv`
  * `. venv/bin/activate`
* Create a blank directory to hold your offer files
  * `mkdir offers`
* Run the utility to generate all the offers. Hint, DERIVATIONS is optional for small wallets (defaults to 1000)
  * `DERIVATIONS=8000 FINGERPRINT=1307711849 python3 inferno.py file.csv offers/`
