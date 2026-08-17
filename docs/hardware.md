# Hardware notes

One camera from the tested four-pack was disassembled for board inspection.
These markings may help identify compatible hardware revisions:

| Component | Observed marking | Interpretation |
| --- | --- | --- |
| Main board | `VP-GC23-DK-2_MAIN V1.0` | VeePai/O-KAM camera platform board |
| Wi-Fi radio | `AIC8800D80` | AICSemi dual-band Wi-Fi 6 radio |
| SPI flash | `XT25F64B` | XTX 64-Mbit (8 MiB) 3.3 V SPI NOR flash |
| Debug pads | `GND`, `TX`, `RX` | Probable 3.3 V UART console; voltage not yet measured |

The main processor was covered by thermal compound. Its identity has not been
confirmed, so no processor model is asserted here.

## Reprogramming outlook

The labeled UART pads and external SPI flash make firmware extraction and
console access plausible. They do not guarantee an unlocked bootloader or a
practical replacement-firmware path. Before connecting a USB-to-UART adapter:

1. Disconnect power and identify ground with a multimeter.
2. Power the board normally and measure the TX idle voltage; do not assume 5 V
   tolerance. A 3.3 V logic adapter is the likely choice.
3. Connect ground and adapter RX to camera TX first, leaving adapter TX
   disconnected, then test common baud rates while capturing boot output.
4. Read and preserve the entire SPI flash with an external programmer before
   attempting writes.
5. Keep the original camera-specific calibration and identity partitions.

Do not power the camera through both its normal supply and a programmer at the
same time. Pin assignments and voltage levels remain unverified.
