<pre>
 __          __     _____  _   _ _____ _   _  _____ 
 \ \        / /\   |  __ \| \ | |_   _| \ | |/ ____|
  \ \  /\  / /  \  | |__) |  \| | | | |  \| | |  __ 
   \ \/  \/ / /\ \ |  _  /| . ` | | | | . ` | | |_ |
    \  /\  / ____ \| | \ \| |\  |_| |_| |\  | |__| |
     \/  \/_/    \_\_|  \_\_| \_|_____|_| \_|\_____|
                                                    
                                                    
</pre>

No warranty, expressed or implied. Please test your specific use case and scenario!

The provided puzzle has been fairly well-tested with XCH royalties, and includes pre-configured maximum amounts of fees subdivided from the original royalty payment held by the puzzle. It is known to NOT support CAT royalties because farmer fees can only be paid in XCH. If you do assign this puzzle hash to an NFT that sells for CAT tokens, you will likely NEVER receive the royalties. While other puzzles will address this limitation, this variation remains as an exhibit of the capabilities of Chialisp.

A previous version of this document used Windows path delimiters "\". Because this process has been most thoroughly tested on *nix systems, we are changing the convention to "/".

# 1. Build

```
cd clsp/p2_royalty_share_equal_max_fee_nocat/
cdv clsp build ./p2_royalty_share_equal_max_fee_nocat.clsp
```

# 2. Curry (Supply Un-Changing Arguments)

1. First argument: List of addresses as hexadecimal puzzle hashes. You will want to become familiar with `cdv encode` and `cdv encode`. Addresses shown below are extremely fake and must not be used.
2. Second argument: Size of list from first argument. While this could be calculated easily in the puzzle, it is unnecessary work to recurse the list and size it. Here, 7.
3. Third argument: The maximum fee, in mojos, you wish to ever pay to have your royalties forwarded from the shared puzzle to its final destination. Choose carefully to strike a balance between wasting large fees in the future and getting starved out of blocks due to insufficient fees. Shown below is a sample value of 50 Million mojos.

```
 cdv clsp curry ./p2_royalty_share_equal_max_fee_nocat.clsp.hex -a '(0x0000000000000000000000000000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000000000000000000000000000 0x0000000000000000000000000000000000000000000000000000000000000000)' -a 7 -a 50000000
 ```

# 3. Obtain Puzzle Hash Address / Puzzle Reveal

The output of the `cdv clsp curry` statement above is your completed puzzle. You just need to copy and paste the whole expression and run it through:

```
opc -H 'THE_WHOLE_PUZZLE_HERE'
opc 'THE_WHOLE_PUZZLE_HERE'
```

The first line is your puzzle hash, as hexadecimal. You will convert it into an address in your next step.

The second line is your puzzle reveal, as hexadecimal. You will need this later.

# 4. Send Test Transaction to Royalty Puzzle Hash Address

```
cdv encode THE_PUZZLE_HASH
```

You may now send any desired amount of XCH to the resulting address in any Chia wallet of your choice.

# 5. Verify Receipt of Test Transaction

Search your block explorer of choice for the transaction sent to the puzzle hash address (after verifying the tx is no longer pending).

# 6. Run the Royalty Share Python Driver

The curried puzzle from step 2 can be saved to a file for ease of running the "Sweeper" program to trigger the royalty share spends to the individual wallets.

```
 python3 ../../royalty_share_spend.py <ROYALTY_ADDRESS> <PATH_TO_CURRIED_ROYALTY_PUZZLE_AS_HEX>
 ```

 If you followed these instructions correctly you should see a SUCCESS message.

# 7. Verify Receipt of Royalty Payments to End Addresses

Give the transaction time to clear the mempool (just a minute or so if fees are reasonable) and then verify there are outgoing transactions from your royalty puzzle hash to your individual royalty recipients' addresses.

# 8. Assign Royalty Address to a Minted NFT

Assign the royalty address to a minted NFT. If you have any remaining fears, sell it to yourself first (accept your own offer) and verify the royalties go from yourself to yourself as expected. 

If all goes well, proceed with your NFT release. If all does not, consider starting a Burn Pile DID to hold your trash while you await release of an NFT melting tool!
