# Prerequisites

You need to install chia-dev-tools and follow the instructions on activating its Python venv.

https://github.com/Chia-Network/chia-dev-tools

# Build

```cdv clsp build .\royalty_share.clsp```

# Curry (Supply Un-Changing Arguments)

1. First argument: List of addresses as hexadecimal puzzle hashes. You will want to become familiar with `cdv encode` and `cdv encode`. Addresses shown below are extremely fake and must not be used.
2. Second argument: Size of list from first argument. While this could be calculated easily in the puzzle, it is unnecessary work to recurse the list and size it. Here, 7.
3. Third argument: The maximum fee, in mojos, you wish to ever pay to have your royalties forwarded from the shared puzzle to its final destination. Choose carefully to strike a balance between wasting large fees in the future and getting starved out of blocks due to insufficient fees. Shown below is a sample value of 50 Million mojos.

```
 cdv clsp curry .\royalty_share.clsp.hex -a '(0x0000000000000000000000000000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000000000000000000000000000)' -a 7 -a 50000000
 ```

# Obtain Puzzle Hash Address / Puzzle Reveal

The output of the `cdv clsp curry` statement above is your completed puzzle. You just need to copy and paste the whole expression and run it through:

```
opc -H 'THE_WHOLE_PUZZLE_HERE'
```

The first line is your puzzle hash, as hexadecimal. You will convert it into an address in your next step.

The second line is your puzzle reveal, as hexadecimal. You will need this later.

# Send Test Transaction to Royalty Puzzle Hash Address

```
cdv encode THE_PUZZLE_HASH
```

You may now send any desired amount of XCH to the resulting address in any Chia wallet of your choice.

# Verify Receipt of Test Transaction

Search your block explorer of choice for the transaction sent to the puzzle hash address (after verifying the tx is no longer pending).

# Invoke Spend of Royalty Puzzle to Royalty Addresses

See spend_template.json and provide the missing elements. Your puzzle solution can be obtained by:

```
opc '(COIN_SPEND_AMOUNT)'
```
such as opc '(5000)' for a 5000 mojo coin

```
 cdv rpc pushtx ./spend.json
 ```

 If you followed these instructions correctly you should see a SUCCESS message.

# Verify Receipt of Royalty Payments to End Addresses

Give the transaction time to clear the mempool (just a minute or so if fees are reasonable) and then verify there are outgoing transactions from your royalty puzzle hash to your individual royalty recipients' addresses.

# Assign Royalty Address to a Minted NFT

Assign the royalty address to a minted NFT. If you have any remaining fears, sell it to yourself first (accept your own offer) and verify the royalties go from yourself to yourself as expected.