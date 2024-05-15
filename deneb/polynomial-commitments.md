# Deneb -- Polynomial Commitments

## Table of contents

<!-- TOC -->
<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->

- [Introduction](#introduction)
- [Custom types](#custom-types)
- [Constants](#constants)
- [Preset](#preset)
  - [Blob](#blob)
  - [Trusted setup](#trusted-setup)
- [Helper functions](#helper-functions)
  - [Bit-reversal permutation](#bit-reversal-permutation)
    - [`is_power_of_two`](#is_power_of_two)
    - [`reverse_bits`](#reverse_bits)
    - [`bit_reversal_permutation`](#bit_reversal_permutation)
  - [BLS12-381 helpers](#bls12-381-helpers)
    - [`multi_exp`](#multi_exp)
    - [`hash_to_bls_field`](#hash_to_bls_field)
    - [`bytes_to_bls_field`](#bytes_to_bls_field)
    - [`bls_field_to_bytes`](#bls_field_to_bytes)
    - [`validate_kzg_g1`](#validate_kzg_g1)
    - [`bytes_to_kzg_commitment`](#bytes_to_kzg_commitment)
    - [`bytes_to_kzg_proof`](#bytes_to_kzg_proof)
    - [`blob_to_polynomial`](#blob_to_polynomial)
    - [`compute_challenge`](#compute_challenge)
    - [`bls_modular_inverse`](#bls_modular_inverse)
    - [`div`](#div)
    - [`g1_lincomb`](#g1_lincomb)
    - [`compute_powers`](#compute_powers)
    - [`compute_roots_of_unity`](#compute_roots_of_unity)
  - [Polynomials](#polynomials)
    - [`evaluate_polynomial_in_evaluation_form`](#evaluate_polynomial_in_evaluation_form)
  - [KZG](#kzg)
    - [`blob_to_kzg_commitment`](#blob_to_kzg_commitment)
    - [`verify_kzg_proof`](#verify_kzg_proof)
    - [`verify_kzg_proof_impl`](#verify_kzg_proof_impl)
    - [`verify_kzg_proof_batch`](#verify_kzg_proof_batch)
    - [`compute_kzg_proof`](#compute_kzg_proof)
    - [`compute_quotient_eval_within_domain`](#compute_quotient_eval_within_domain)
    - [`compute_kzg_proof_impl`](#compute_kzg_proof_impl)
    - [`compute_blob_kzg_proof`](#compute_blob_kzg_proof)
    - [`verify_blob_kzg_proof`](#verify_blob_kzg_proof)
    - [`verify_blob_kzg_proof_batch`](#verify_blob_kzg_proof_batch)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->
<!-- /TOC -->

## Introduction

This document specifies basic polynomial operations and KZG polynomial commitment operations that are essential for the implementation of the EIP-4844 feature in the Deneb specification. The implementations are not optimized for performance, but readability. All practical implementations should optimize the polynomial operations.

Functions flagged as "Public method" MUST be provided by the underlying KZG library as public functions. All other functions are private functions used internally by the KZG library.

Public functions MUST accept raw bytes as input and perform the required cryptographic normalization before invoking any internal functions.

## Custom types

| Name | SSZ equivalent | Description |
| - | - | - |
| `G1Point` | `Bytes48` | |
| `G2Point` | `Bytes96` | |
| `BLSFieldElement` | `uint256` | Validation: `x < BLS_MODULUS` |
| `KZGCommitment` | `Bytes48` | Validation: Perform [BLS standard's](https://datatracker.ietf.org/doc/html/draft-irtf-cfrg-bls-signature-04#section-2.5) "KeyValidate" check but do allow the identity point |
| `KZGProof` | `Bytes48` | Same as for `KZGCommitment` |
| `Polynomial` | `Vector[BLSFieldElement, FIELD_ELEMENTS_PER_BLOB]` | A polynomial in evaluation form |
| `Blob` | `ByteVector[BYTES_PER_FIELD_ELEMENT * FIELD_ELEMENTS_PER_BLOB]` | A basic data blob |

## Constants

| Name | Value | Notes |
| - | - | - |
| `BLS_MODULUS` | `52435875175126190479447740508185965837690552500527637822603658699938581184513` | Scalar field modulus of BLS12-381 |
| `BYTES_PER_COMMITMENT` | `uint64(48)` | The number of bytes in a KZG commitment |
| `BYTES_PER_PROOF` | `uint64(48)` | The number of bytes in a KZG proof |
| `BYTES_PER_FIELD_ELEMENT` | `uint64(32)` | Bytes used to encode a BLS scalar field element |
| `BYTES_PER_BLOB` | `uint64(BYTES_PER_FIELD_ELEMENT * FIELD_ELEMENTS_PER_BLOB)` | The number of bytes in a blob |
| `G1_POINT_AT_INFINITY` | `Bytes48(b'\xc0' + b'\x00' * 47)` | Serialized form of the point at infinity on the G1 group |
| `KZG_ENDIANNESS` | `'big'` | The endianness of the field elements including blobs |
| `PRIMITIVE_ROOT_OF_UNITY` | `7` | The primitive root of unity from which all roots of unity should be derived |

## Preset

### Blob

| Name | Value |
| - | - |
| `FIELD_ELEMENTS_PER_BLOB` | `uint64(4096)` |
| `FIAT_SHAMIR_PROTOCOL_DOMAIN` | `b'FSBLOBVERIFY_V1_'` |
| `RANDOM_CHALLENGE_KZG_BATCH_DOMAIN` | `b'RCKZGBATCH___V1_'` |

### Trusted setup

| Name | Value |
| - | - |
| `KZG_SETUP_G2_LENGTH` | `65` |
| `KZG_SETUP_G1_MONOMIAL` | `Vector[G1Point, FIELD_ELEMENTS_PER_BLOB]` |
| `KZG_SETUP_G1_LAGRANGE` | `Vector[G1Point, FIELD_ELEMENTS_PER_BLOB]` |
| `KZG_SETUP_G2_MONOMIAL` | `Vector[G2Point, KZG_SETUP_G2_LENGTH]` |

KZG commitments depend on a [trusted setup](https://vitalik.eth.limo/general/2022/03/14/trustedsetup.html) to generate elliptic curve commitments to a series of powers of a secret number `s`. That is, these points are of the form `[G1, G1 * s, G1 * s**2 ... G1 * s**4095]` and `[G2, G2 * s, G2 * s**2 ... G2 * s**64]`. Nobody knows `s`, because [over 140,000 participants](https://ceremony.ethereum.org/) mixed their randomness to produce the trusted setup, and if even one of those was honest, the trusted setup is secure.

## Aside: what evaluation points are we using?

As we mentioned above, the 4096 values in the deserialized blob are evaluations of a polynomial `P` at a set of 4096 points, and the 8192 values in the extended data are evaluations at _another_ 4096 points. But which points? Theoretically, any choice (even `0...8191`) would be valid, but some choices lead to much more efficient algorithms than others. We use **powers of a root of unity, in bit-reversal permutation**. Let's unpack this.

First, "powers of a root of unity". We compute a value `w`, which satisfies `w ** 8192 == 1` modulo the BLS modulus, and where `w ** 4096` is not 1. You can think of the powers of `w` as being arranged in a circle. Any two points that are opposites on the circle are additive opposites of each other: if `w_k = w**k`, then the opposite point on the circle would be `w_{k + 4096} = w**(k + 4096) = w**k * w**4096 = w_k * -1`. The last identity that we used there, `w**4096 = -1`, follows from the fact that `w ** 8192 == 1` and `w ** 4096` is not 1: just like in real numbers, in a field the only two square roots of 1 are 1 and -1!

This circle arrangement is convenient for efficient algorithms for transforming from evaluations to coordinates and back, most notably the [Fast Fourier transform](https://vitalik.eth.limo/general/2019/05/12/fft.html).

The value `PRIMITIVE_ROOT_OF_UNITY = 7` set in the parameters above is used to generate `w`. We know that `PRIMITIVE_ROOT_OF_UNITY ** (BLS_MODULUS - 1) = 1` (because of [Fermat's little theorem](https://en.wikipedia.org/wiki/Fermat%27s_little_theorem)), and we chose `PRIMITIVE_ROOT_OF_UNITY` so that no smaller power of it equals 1 (that's the definition of "primitive root"). The desired property of `w` is that `w**8192` is the smallest power of `w` that equals 1. Hence, we generate `w` by computing `PRIMITIVE_ROOT_OF_UNITY ** ((BLS_MODULUS - 1) / 8192)`.

Now, "bit reversal permutation". As it turns out, if you want to do operations involving multiple evaluation points, it's often much mathematically cleaner if they are related to each other by high powers of 2 that are near the full size of the circle (here, 8192). For example, `(X - w_k) * (X - w_{k + 4096}) = (X^2 - w_2k)`. Similarly, `(X - w_k) * (X - w_{k + 512}) * ... * (X - w_{k + 512 * 15}) = (X^16 - x_16k)`. The formulas for eg. `(X - w_k) * (X - w_{k + 1}) * ... * (X - w_{k + 15})` are much less clean.

In data availability sampling, we put multiple adjacent evaluations together into one sample for efficiency. Generating KZG proofs for these samples is much more efficient if the evaluation points that are used in these adjacent evaluations are related by high powers of 2, like in the examples above. To accomplish this, we order the evaluation points in a very particular order. The order can be constructed recursively as follows:

```
def mk_order(n):
    if n == 0:
        return [0]
    else:
        prev = mk_order(n-1)
        return [x*2 for x in prev] + [x*2+1 for x in prev]
```

Here are the initial outputs:

```
>>> mk_order(0)
[0]
>>> mk_order(1)
[0, 1]
>>> mk_order(2)
[0, 2, 1, 3]
>>> mk_order(3)
[0, 4, 2, 6, 1, 5, 3, 7]
>>> mk_order(4)
[0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15]
```

That is, if we were to only have 16 total points (instead of 8192), the first point would be `P(w**0)`, the second would be `P(w**8)`, the third would be `P(w**4)`, etc.

Notice that values that are close to each other are related by high powers of 2. In fact, if we compute `mk_order(13)`, and take any adjacent aligned slice of 16 values, we would find that they are related by a difference of 512, just like in our ideal example above:

```
>>> mk_order(13)[16*42:16*43]
[168, 4264, 2216, 6312, 1192, 5288, 3240, 7336, 680, 4776, 2728, 6824, 1704, 5800, 3752, 7848]
```

This is the entire set of values `168 + 512k` for `k = 0..15`. As another bonus, notice that the first 4096 outputs are actually all multiples of a "sub-root of unity", `w**2`, whose powers form a smaller circle of size 4096 (as `(w**2)**4096` circles back to 1). Hence, the values "in the serialized blob", which only uses the first 4096 positions, are all evaluations at powers of `w**2`; meanwhile, the samples are at powers of `w`, both even and odd.

## Helper functions

### Bit-reversal permutation

All polynomials (which are always given in Lagrange form) should be interpreted as being in
bit-reversal permutation. In practice, clients can implement this by storing the lists
`KZG_SETUP_G1_LAGRANGE` and roots of unity in bit-reversal permutation, so these functions only
have to be called once at startup.

#### `is_power_of_two`

```python
def is_power_of_two(value: int) -> bool:
    """
    Check if ``value`` is a power of two integer.
    """
    return (value > 0) and (value & (value - 1) == 0)
```

#### `reverse_bits`

```python
def reverse_bits(n: int, order: int) -> int:
    """
    Reverse the bit order of an integer ``n``.
    """
    assert is_power_of_two(order)
    # Convert n to binary with the same number of bits as "order" - 1, then reverse its bit order
    return int(('{:0' + str(order.bit_length() - 1) + 'b}').format(n)[::-1], 2)
```

#### `bit_reversal_permutation`

```python
def bit_reversal_permutation(sequence: Sequence[T]) -> Sequence[T]:
    """
    Return a copy with bit-reversed permutation. The permutation is an involution (inverts itself).

    The input and output are a sequence of generic type ``T`` objects.
    """
    return [sequence[reverse_bits(i, len(sequence))] for i in range(len(sequence))]
```

### BLS12-381 helpers


#### `multi_exp`

This function performs a multi-scalar multiplication between `points` and `integers`. `points` can either be in G1 or G2.

```python
def multi_exp(points: Sequence[TPoint],
              integers: Sequence[uint64]) -> Sequence[TPoint]:
    # pylint: disable=unused-argument
    ...
```

Note that "multi-exponentiation", "multi-scalar multiplication" and "linear combination" all mean the same thing. Part of the reason why is that there were two separate cryptographic traditions, one of which viewed the operation to combine two elliptic curve points as being "addition", and the other which viewed it as "multiplication". "Linear combination" is a [long-established term](https://en.wikipedia.org/wiki/Linear_combination) for "take a sequence of objects, and a sequence of constants, multiply the i'th object by the i'th constant, and add the results".

This problem is of interest because there are [much more efficient algorithms](https://ethresear.ch/t/simple-guide-to-fast-linear-combinations-aka-multiexponentiations/7238) to compute these operations than a naive "walk through the lists, multiply and add" approach.

#### `hash_to_bls_field`

```python
def hash_to_bls_field(data: bytes) -> BLSFieldElement:
    """
    Hash ``data`` and convert the output to a BLS scalar field element.
    The output is not uniform over the BLS field.
    """
    hashed_data = hash(data)
    return BLSFieldElement(int.from_bytes(hashed_data, KZG_ENDIANNESS) % BLS_MODULUS)
```

#### `bytes_to_bls_field`

```python
def bytes_to_bls_field(b: Bytes32) -> BLSFieldElement:
    """
    Convert untrusted bytes to a trusted and validated BLS scalar field element.
    This function does not accept inputs greater than the BLS modulus.
    """
    field_element = int.from_bytes(b, KZG_ENDIANNESS)
    assert field_element < BLS_MODULUS
    return BLSFieldElement(field_element)
```

#### `bls_field_to_bytes`

```python
def bls_field_to_bytes(x: BLSFieldElement) -> Bytes32:
    return int.to_bytes(x % BLS_MODULUS, 32, KZG_ENDIANNESS)
```

#### `validate_kzg_g1`

```python
def validate_kzg_g1(b: Bytes48) -> None:
    """
    Perform BLS validation required by the types `KZGProof` and `KZGCommitment`.
    """
    if b == G1_POINT_AT_INFINITY:
        return

    assert bls.KeyValidate(b)
```

#### `bytes_to_kzg_commitment`

```python
def bytes_to_kzg_commitment(b: Bytes48) -> KZGCommitment:
    """
    Convert untrusted bytes into a trusted and validated KZGCommitment.
    """
    validate_kzg_g1(b)
    return KZGCommitment(b)
```

#### `bytes_to_kzg_proof`

```python
def bytes_to_kzg_proof(b: Bytes48) -> KZGProof:
    """
    Convert untrusted bytes into a trusted and validated KZGProof.
    """
    validate_kzg_g1(b)
    return KZGProof(b)
```

#### `blob_to_polynomial`

```python
def blob_to_polynomial(blob: Blob) -> Polynomial:
    """
    Convert a blob to list of BLS field scalars.
    """
    polynomial = Polynomial()
    for i in range(FIELD_ELEMENTS_PER_BLOB):
        value = bytes_to_bls_field(blob[i * BYTES_PER_FIELD_ELEMENT: (i + 1) * BYTES_PER_FIELD_ELEMENT])
        polynomial[i] = value
    return polynomial
```

Note that the "polynomial" outputted by this is a list of _evaluations_, not a list of _coefficients_.

#### `compute_challenge`

Suppose that a client receives a blob from a `BlobSidecar`, and they want to check if it matches the KZG commitment in the `BeaconBlock`. One way to do this would be to compute the KZG commitment from the blob directly, and check if it matches. However, this is too slow to do with many blobs. Instead, we use a clever cryptographic trick. We hash the blob and the commitment to generate a random point. We require the beacon block to provide an evaluation of the polynomial at that point, along with a KZG evaluation proof. The client can then evaluate the polynomial from the blob directly, and check that the two evaluations match. This is a common random checking trick used in cryptography: to verify that two polynomials `P` and `Q` are different, choose a random `x`, and verify that `P(x) = Q(x)`. It works as long as the domain from which `x` is chosen is large enough; in this case, it is (because `BLS_MODULUS` is a 256-bit number).

This function computes this challenge point `x`.

```python
def compute_challenge(blob: Blob,
                      commitment: KZGCommitment) -> BLSFieldElement:
    """
    Return the Fiat-Shamir challenge required by the rest of the protocol.
    """

    # Append the degree of the polynomial as a domain separator
    degree_poly = int.to_bytes(FIELD_ELEMENTS_PER_BLOB, 16, KZG_ENDIANNESS)
    data = FIAT_SHAMIR_PROTOCOL_DOMAIN + degree_poly

    data += blob
    data += commitment

    # Transcript has been prepared: time to create the challenge
    return hash_to_bls_field(data)
```

#### `bls_modular_inverse`

```python
def bls_modular_inverse(x: BLSFieldElement) -> BLSFieldElement:
    """
    Compute the modular inverse of x (for x != 0)
    i.e. return y such that x * y % BLS_MODULUS == 1
    """
    assert (int(x) % BLS_MODULUS) != 0
    return BLSFieldElement(pow(x, -1, BLS_MODULUS))
```

#### `div`

```python
def div(x: BLSFieldElement, y: BLSFieldElement) -> BLSFieldElement:
    """
    Divide two field elements: ``x`` by `y``.
    """
    return BLSFieldElement((int(x) * int(bls_modular_inverse(y))) % BLS_MODULUS)
```

#### `g1_lincomb`

```python
def g1_lincomb(points: Sequence[KZGCommitment], scalars: Sequence[BLSFieldElement]) -> KZGCommitment:
    """
    BLS multiscalar multiplication in G1. This can be naively implemented using double-and-add.
    """
    assert len(points) == len(scalars)

    if len(points) == 0:
        return bls.G1_to_bytes48(bls.Z1())

    points_g1 = []
    for point in points:
        points_g1.append(bls.bytes48_to_G1(point))

    result = bls.multi_exp(points_g1, scalars)
    return KZGCommitment(bls.G1_to_bytes48(result))
```

#### `compute_powers`

```python
def compute_powers(x: BLSFieldElement, n: uint64) -> Sequence[BLSFieldElement]:
    """
    Return ``x`` to power of [0, n-1], if n > 0. When n==0, an empty array is returned.
    """
    current_power = 1
    powers = []
    for _ in range(n):
        powers.append(BLSFieldElement(current_power))
        current_power = current_power * int(x) % BLS_MODULUS
    return powers
```

#### `compute_roots_of_unity`

```python
def compute_roots_of_unity(order: uint64) -> Sequence[BLSFieldElement]:
    """
    Return roots of unity of ``order``.
    """
    assert (BLS_MODULUS - 1) % int(order) == 0
    root_of_unity = BLSFieldElement(pow(PRIMITIVE_ROOT_OF_UNITY, (BLS_MODULUS - 1) // int(order), BLS_MODULUS))
    return compute_powers(root_of_unity, order)
```

### Polynomials

#### `evaluate_polynomial_in_evaluation_form`

```python
def evaluate_polynomial_in_evaluation_form(polynomial: Polynomial,
                                           z: BLSFieldElement) -> BLSFieldElement:
    """
    Evaluate a polynomial (in evaluation form) at an arbitrary point ``z``.
    - When ``z`` is in the domain, the evaluation can be found by indexing the polynomial at the
    position that ``z`` is in the domain.
    - When ``z`` is not in the domain, the barycentric formula is used:
       f(z) = (z**WIDTH - 1) / WIDTH  *  sum_(i=0)^WIDTH  (f(DOMAIN[i]) * DOMAIN[i]) / (z - DOMAIN[i])
    """
    width = len(polynomial)
    assert width == FIELD_ELEMENTS_PER_BLOB
    inverse_width = bls_modular_inverse(BLSFieldElement(width))

    roots_of_unity_brp = bit_reversal_permutation(compute_roots_of_unity(FIELD_ELEMENTS_PER_BLOB))

    # If we are asked to evaluate within the domain, we already know the answer
    if z in roots_of_unity_brp:
        eval_index = roots_of_unity_brp.index(z)
        return BLSFieldElement(polynomial[eval_index])

    result = 0
    for i in range(width):
        a = BLSFieldElement(int(polynomial[i]) * int(roots_of_unity_brp[i]) % BLS_MODULUS)
        b = BLSFieldElement((int(BLS_MODULUS) + int(z) - int(roots_of_unity_brp[i])) % BLS_MODULUS)
        result += int(div(a, b) % BLS_MODULUS)
    result = result * int(BLS_MODULUS + pow(z, width, BLS_MODULUS) - 1) * int(inverse_width)
    return BLSFieldElement(result % BLS_MODULUS)
```

Given a polynomial in evaluation form (which is what a serialized blob is), directly evaluate it at a given point `z`. It's possible to do this using the [barycentric formula](https://tobydriscoll.net/fnc-julia/globalapprox/barycentric.html), which the above function implements. It takes `O(N)` arithmetic operations.

### KZG

KZG core functions. These are also defined in Deneb execution specs.

#### `blob_to_kzg_commitment`

```python
def blob_to_kzg_commitment(blob: Blob) -> KZGCommitment:
    """
    Public method.
    """
    assert len(blob) == BYTES_PER_BLOB
    return g1_lincomb(bit_reversal_permutation(KZG_SETUP_G1_LAGRANGE), blob_to_polynomial(blob))
```

#### `verify_kzg_proof`

```python
def verify_kzg_proof(commitment_bytes: Bytes48,
                     z_bytes: Bytes32,
                     y_bytes: Bytes32,
                     proof_bytes: Bytes48) -> bool:
    """
    Verify KZG proof that ``p(z) == y`` where ``p(z)`` is the polynomial represented by ``polynomial_kzg``.
    Receives inputs as bytes.
    Public method.
    """
    assert len(commitment_bytes) == BYTES_PER_COMMITMENT
    assert len(z_bytes) == BYTES_PER_FIELD_ELEMENT
    assert len(y_bytes) == BYTES_PER_FIELD_ELEMENT
    assert len(proof_bytes) == BYTES_PER_PROOF

    return verify_kzg_proof_impl(bytes_to_kzg_commitment(commitment_bytes),
                                 bytes_to_bls_field(z_bytes),
                                 bytes_to_bls_field(y_bytes),
                                 bytes_to_kzg_proof(proof_bytes))
```

This is the function that verifies a KZG proof of evaluation: if `commitment_bytes` is a commitment to `P`, it's only possible to generate a valid proof `proof_bytes` for a given `z_bytes` and `y_bytes` if `P(z) = y`.


#### `verify_kzg_proof_impl`

```python
def verify_kzg_proof_impl(commitment: KZGCommitment,
                          z: BLSFieldElement,
                          y: BLSFieldElement,
                          proof: KZGProof) -> bool:
    """
    Verify KZG proof that ``p(z) == y`` where ``p(z)`` is the polynomial represented by ``polynomial_kzg``.
    """
    # Verify: P - y = Q * (X - z)
    X_minus_z = bls.add(
        bls.bytes96_to_G2(KZG_SETUP_G2_MONOMIAL[1]),
        bls.multiply(bls.G2(), (BLS_MODULUS - z) % BLS_MODULUS),
    )
    P_minus_y = bls.add(bls.bytes48_to_G1(commitment), bls.multiply(bls.G1(), (BLS_MODULUS - y) % BLS_MODULUS))
    return bls.pairing_check([
        [P_minus_y, bls.neg(bls.G2())],
        [bls.bytes48_to_G1(proof), X_minus_z]
    ])
```

Verifying a KZG proof requires computing an [elliptic curve pairing](https://vitalik.eth.limo/general/2017/01/14/exploring_ecp.html). Pairings with KZG commitments have the property that `e(commit(A), commit(B)) = e(commit(C), commit(1))` only if, as polynomials, `C = A * B`. The standard way to prove that `P(z) = y`, is to require a commitment to `Q = (P - y) / (X - z)`. The verifier computes `commit(X - z)` and `commit(P - y)`, and then uses a pairing to check that the product of those two equals to `Q`. Both of those commitmetns are easy to compute in O(1) time: `commit(X - z)` directly, ad `commit(P - y)` as `commit(P) - commit(y)`, where `commit(P)` was already provided. Because pairings need to take a `G1` element and a `G2` element as input, we compute `(X - z)` in G2 form.

#### `verify_kzg_proof_batch`

```python
def verify_kzg_proof_batch(commitments: Sequence[KZGCommitment],
                           zs: Sequence[BLSFieldElement],
                           ys: Sequence[BLSFieldElement],
                           proofs: Sequence[KZGProof]) -> bool:
    """
    Verify multiple KZG proofs efficiently.
    """

    assert len(commitments) == len(zs) == len(ys) == len(proofs)

    # Compute a random challenge. Note that it does not have to be computed from a hash,
    # r just has to be random.
    degree_poly = int.to_bytes(FIELD_ELEMENTS_PER_BLOB, 8, KZG_ENDIANNESS)
    num_commitments = int.to_bytes(len(commitments), 8, KZG_ENDIANNESS)
    data = RANDOM_CHALLENGE_KZG_BATCH_DOMAIN + degree_poly + num_commitments

    # Append all inputs to the transcript before we hash
    for commitment, z, y, proof in zip(commitments, zs, ys, proofs):
        data += commitment \
            + int.to_bytes(z, BYTES_PER_FIELD_ELEMENT, KZG_ENDIANNESS) \
            + int.to_bytes(y, BYTES_PER_FIELD_ELEMENT, KZG_ENDIANNESS) \
            + proof

    r = hash_to_bls_field(data)
    r_powers = compute_powers(r, len(commitments))

    # Verify: e(sum r^i proof_i, [s]) ==
    # e(sum r^i (commitment_i - [y_i]) + sum r^i z_i proof_i, [1])
    proof_lincomb = g1_lincomb(proofs, r_powers)
    proof_z_lincomb = g1_lincomb(
        proofs,
        [BLSFieldElement((int(z) * int(r_power)) % BLS_MODULUS) for z, r_power in zip(zs, r_powers)],
    )
    C_minus_ys = [bls.add(bls.bytes48_to_G1(commitment), bls.multiply(bls.G1(), (BLS_MODULUS - y) % BLS_MODULUS))
                  for commitment, y in zip(commitments, ys)]
    C_minus_y_as_KZGCommitments = [KZGCommitment(bls.G1_to_bytes48(x)) for x in C_minus_ys]
    C_minus_y_lincomb = g1_lincomb(C_minus_y_as_KZGCommitments, r_powers)
    
    return bls.pairing_check([
        [bls.bytes48_to_G1(proof_lincomb), bls.neg(bls.bytes96_to_G2(KZG_SETUP_G2_MONOMIAL[1]))],
        [bls.add(bls.bytes48_to_G1(C_minus_y_lincomb), bls.bytes48_to_G1(proof_z_lincomb)), bls.G2()]
    ])
```

This is an optimized algorithm for verifying many KZG evaluation proofs at the same time.

#### `compute_kzg_proof`

```python
def compute_kzg_proof(blob: Blob, z_bytes: Bytes32) -> Tuple[KZGProof, Bytes32]:
    """
    Compute KZG proof at point `z` for the polynomial represented by `blob`.
    Do this by computing the quotient polynomial in evaluation form: q(x) = (p(x) - p(z)) / (x - z).
    Public method.
    """
    assert len(blob) == BYTES_PER_BLOB
    assert len(z_bytes) == BYTES_PER_FIELD_ELEMENT
    polynomial = blob_to_polynomial(blob)
    proof, y = compute_kzg_proof_impl(polynomial, bytes_to_bls_field(z_bytes))
    return proof, y.to_bytes(BYTES_PER_FIELD_ELEMENT, KZG_ENDIANNESS)
```

#### `compute_quotient_eval_within_domain`

```python
def compute_quotient_eval_within_domain(z: BLSFieldElement,
                                        polynomial: Polynomial,
                                        y: BLSFieldElement
                                        ) -> BLSFieldElement:
    """
    Given `y == p(z)` for a polynomial `p(x)`, compute `q(z)`: the KZG quotient polynomial evaluated at `z` for the
    special case where `z` is in roots of unity.

    For more details, read https://dankradfeist.de/ethereum/2021/06/18/pcs-multiproofs.html section "Dividing
    when one of the points is zero". The code below computes q(x_m) for the roots of unity special case.
    """
    roots_of_unity_brp = bit_reversal_permutation(compute_roots_of_unity(FIELD_ELEMENTS_PER_BLOB))
    result = 0
    for i, omega_i in enumerate(roots_of_unity_brp):
        if omega_i == z:  # skip the evaluation point in the sum
            continue

        f_i = int(BLS_MODULUS) + int(polynomial[i]) - int(y) % BLS_MODULUS
        numerator = f_i * int(omega_i) % BLS_MODULUS
        denominator = int(z) * (int(BLS_MODULUS) + int(z) - int(omega_i)) % BLS_MODULUS
        result += int(div(BLSFieldElement(numerator), BLSFieldElement(denominator)))

    return BLSFieldElement(result % BLS_MODULUS)
```

#### `compute_kzg_proof_impl`

```python
def compute_kzg_proof_impl(polynomial: Polynomial, z: BLSFieldElement) -> Tuple[KZGProof, BLSFieldElement]:
    """
    Helper function for `compute_kzg_proof()` and `compute_blob_kzg_proof()`.
    """
    roots_of_unity_brp = bit_reversal_permutation(compute_roots_of_unity(FIELD_ELEMENTS_PER_BLOB))

    # For all x_i, compute p(x_i) - p(z)
    y = evaluate_polynomial_in_evaluation_form(polynomial, z)
    polynomial_shifted = [BLSFieldElement((int(p) - int(y)) % BLS_MODULUS) for p in polynomial]

    # For all x_i, compute (x_i - z)
    denominator_poly = [BLSFieldElement((int(x) - int(z)) % BLS_MODULUS)
                        for x in roots_of_unity_brp]

    # Compute the quotient polynomial directly in evaluation form
    quotient_polynomial = [BLSFieldElement(0)] * FIELD_ELEMENTS_PER_BLOB
    for i, (a, b) in enumerate(zip(polynomial_shifted, denominator_poly)):
        if b == 0:
            # The denominator is zero hence `z` is a root of unity: we must handle it as a special case
            quotient_polynomial[i] = compute_quotient_eval_within_domain(roots_of_unity_brp[i], polynomial, y)
        else:
            # Compute: q(x_i) = (p(x_i) - p(z)) / (x_i - z).
            quotient_polynomial[i] = div(a, b)

    return KZGProof(g1_lincomb(bit_reversal_permutation(KZG_SETUP_G1_LAGRANGE), quotient_polynomial)), y
```

#### `compute_blob_kzg_proof`

```python
def compute_blob_kzg_proof(blob: Blob, commitment_bytes: Bytes48) -> KZGProof:
    """
    Given a blob, return the KZG proof that is used to verify it against the commitment.
    This method does not verify that the commitment is correct with respect to `blob`.
    Public method.
    """
    assert len(blob) == BYTES_PER_BLOB
    assert len(commitment_bytes) == BYTES_PER_COMMITMENT
    commitment = bytes_to_kzg_commitment(commitment_bytes)
    polynomial = blob_to_polynomial(blob)
    evaluation_challenge = compute_challenge(blob, commitment)
    proof, _ = compute_kzg_proof_impl(polynomial, evaluation_challenge)
    return proof
```

See the more detailed description of what's going on in [`compute_challenge`](#compute_challenge).

#### `verify_blob_kzg_proof`

```python
def verify_blob_kzg_proof(blob: Blob,
                          commitment_bytes: Bytes48,
                          proof_bytes: Bytes48) -> bool:
    """
    Given a blob and a KZG proof, verify that the blob data corresponds to the provided commitment.

    Public method.
    """
    assert len(blob) == BYTES_PER_BLOB
    assert len(commitment_bytes) == BYTES_PER_COMMITMENT
    assert len(proof_bytes) == BYTES_PER_PROOF

    commitment = bytes_to_kzg_commitment(commitment_bytes)

    polynomial = blob_to_polynomial(blob)
    evaluation_challenge = compute_challenge(blob, commitment)

    # Evaluate polynomial at `evaluation_challenge`
    y = evaluate_polynomial_in_evaluation_form(polynomial, evaluation_challenge)

    # Verify proof
    proof = bytes_to_kzg_proof(proof_bytes)
    return verify_kzg_proof_impl(commitment, evaluation_challenge, y, proof)
```

See the more detailed description of what's going on in [`compute_challenge`](#compute_challenge).

#### `verify_blob_kzg_proof_batch`

```python
def verify_blob_kzg_proof_batch(blobs: Sequence[Blob],
                                commitments_bytes: Sequence[Bytes48],
                                proofs_bytes: Sequence[Bytes48]) -> bool:
    """
    Given a list of blobs and blob KZG proofs, verify that they correspond to the provided commitments.
    Will return True if there are zero blobs/commitments/proofs.
    Public method.
    """

    assert len(blobs) == len(commitments_bytes) == len(proofs_bytes)

    commitments, evaluation_challenges, ys, proofs = [], [], [], []
    for blob, commitment_bytes, proof_bytes in zip(blobs, commitments_bytes, proofs_bytes):
        assert len(blob) == BYTES_PER_BLOB
        assert len(commitment_bytes) == BYTES_PER_COMMITMENT
        assert len(proof_bytes) == BYTES_PER_PROOF
        commitment = bytes_to_kzg_commitment(commitment_bytes)
        commitments.append(commitment)
        polynomial = blob_to_polynomial(blob)
        evaluation_challenge = compute_challenge(blob, commitment)
        evaluation_challenges.append(evaluation_challenge)
        ys.append(evaluate_polynomial_in_evaluation_form(polynomial, evaluation_challenge))
        proofs.append(bytes_to_kzg_proof(proof_bytes))

    return verify_kzg_proof_batch(commitments, evaluation_challenges, ys, proofs)
```

Use `verify_kzg_proof_batch` to verify multiple blob proofs at the same time.
