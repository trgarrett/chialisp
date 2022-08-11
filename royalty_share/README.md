<pre>
 __          __     _____  _   _ _____ _   _  _____ 
 \ \        / /\   |  __ \| \ | |_   _| \ | |/ ____|
  \ \  /\  / /  \  | |__) |  \| | | | |  \| | |  __ 
   \ \/  \/ / /\ \ |  _  /| . ` | | | | . ` | | |_ |
    \  /\  / ____ \| | \ \| |\  |_| |_| |\  | |__| |
     \/  \/_/    \_\_|  \_\_| \_|_____|_| \_|\_____|
                                                                                                 
</pre>

Do your own research. Your mileage may vary. No warranty, expressed or implied. These puzzles are often configurable in ways that you may come to regret. Test, test, test before any significant funds are at risk!

See the individual puzzle directories under clsp/p2_* for detailed instructions on each option (README.md).

# Prerequisites

You need to install chia-dev-tools and follow the instructions on activating its Python venv. For proper CAT2 support, you will want to make sure you upgrade chia-blockchain via pip up to version 1.5.0+

https://github.com/Chia-Network/chia-dev-tools


# General Flow

1.  Build puzzle Chialisp code
2.  Curry (Supply Un-changing Arguments)
3.  Obtain Puzzle Hash Address / Puzzle Reveal
4.  Send Test Transaction to Royalty Puzzle Hash Address
5.  Verify Receipt of Test Transaction
6.  Run the Royalty Share Python Driver
7.  Verify Receipt of Royalty Payments to End Addresses
8.  Assign Royalty Address to a Minted NFT