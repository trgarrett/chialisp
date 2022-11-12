<pre>
 __          __     _____  _   _ _____ _   _  _____ 
 \ \        / /\   |  __ \| \ | |_   _| \ | |/ ____|
  \ \  /\  / /  \  | |__) |  \| | | | |  \| | |  __ 
   \ \/  \/ / /\ \ |  _  /| . ` | | | | . ` | | |_ |
    \  /\  / ____ \| | \ \| |\  |_| |_| |\  | |__| |
     \/  \/_/    \_\_|  \_\_| \_|_____|_| \_|\_____|
                                                    
                                                    
</pre>

No warranty, expressed or implied. Please test your specific use case and scenario!

This puzzle is meant to support both XCH and CAT2 royalties equally well, while allowing the user to provide an arbitrary list of addresses and proportionate allocations. This puzzle is incorporated from the draft of CHIP-0008 (https://github.com/Chia-Network/chips/pull/30).

No fees are provided by the puzzle itself, but the Python driver should be able to be modified to inject XCH fees into a spend bundle. Please wait for this update, or make it yourself,
before commiting large funds to this--they wouldn't be definitively lost, but you probably wouldn't want to wait years for a single royalty spend to find its way through the chain either!

# 1. Build

```
cdv clsp build ./p2_royalty_share_arbitrary_shares_rest_to_last.clsp
```

# 2. Curry (Supply Un-Changing Arguments)

See puzzle for more detailed argument description

Argument: PAYOUT_SCHEME
    List of 2 element lists (pairs) where the first 
    element is the recipient puzzlehash and the second element is a proportion the recipient should receive, as compared to other recipients.

In this example, the parties will split 60% to deadbeef and 40% to f00f with dangling mojos added to the share of the last recipient (f00f in this case). The cost to execute this puzzle will scale up with 
large numbers of addresses, so they should be avoided.

```
 cdv clsp curry ./p2_royalty_share_arbitrary_shares_rest_to_last.clsp.hex -a '((0x00000000000000000000000000000000000000000000000000000000deadbeef 6000) (0x000000000000000000000000000000000000000000000000000000000000f00f 4000))'
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

After validating steps 5-7 with XCH, feel free to come back and re-validate with a CAT (you will likely need to register its asset ID in royalty_share_spend.py -- PRs happily welcomed to make this data driven via an external API).

# 5. Verify Receipt of Test Transaction

Search your block explorer of choice for the transaction sent to the puzzle hash address (after verifying the tx is no longer pending).

# 6. Run the Royalty Share Python Driver

The curried puzzle from step 2 can be saved to a file for ease of running the "Sweeper" program to trigger the royalty share spends to the individual wallets.

```
 python3 ../../royalty_share_spend.py <ROYALTY_ADDRESS> <PATH_TO_CURRIED_ROYALTY_PUZZLE_AS_HEX>
 ```

 If you followed these instructions correctly you should see a SUCCESS message. If blocks have room, it might even go through without fees!

# 7. Verify Receipt of Royalty Payments to End Addresses

Give the transaction time to clear the mempool (just a minute or so if fees are reasonable) and then verify there are outgoing transactions from your royalty puzzle hash to your individual royalty recipients' addresses.

# 8. Assign Royalty Address to a Minted NFT

Assign the royalty address to a minted NFT. If you have any remaining fears, sell it to yourself first (accept your own offer) and verify the royalties go from yourself to yourself as expected. 

If all goes well, proceed with your NFT release. If all does not, consider starting a Burn Pile DID to hold your trash while you await release of an NFT melting tool!


