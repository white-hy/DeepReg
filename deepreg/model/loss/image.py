"""
Module provides different loss functions for calculating the dissimilarities between images.
"""
import tensorflow as tf

EPS = 1.0e-6  # epsilon to prevent NaN


def dissimilarity_fn(
    y_true: tf.Tensor, y_pred: tf.Tensor, name: str, **kwargs
) -> tf.Tensor:
    """

    :param y_true: fixed_image, shape = (batch, f_dim1, f_dim2, f_dim3)
    :param y_pred: warped_moving_image, shape = (batch, f_dim1, f_dim2, f_dim3)
    :param name: name of the dissimilarity function
    :param kwargs: absorb additional parameters
    :return: shape = (batch,)
    """
    assert name in ["lncc", "ssd", "gmi"]
    # shape = (batch, f_dim1, f_dim2, f_dim3, 1)
    y_true = tf.expand_dims(y_true, axis=4)
    y_pred = tf.expand_dims(y_pred, axis=4)
    if name == "lncc":
        return -local_normalized_cross_correlation(y_true, y_pred, **kwargs)
    elif name == "ssd":
        return ssd(y_true, y_pred)
    elif name == "gmi":
        return -global_mutual_information(y_true, y_pred)
    else:
        raise ValueError("Unknown loss type.")


def local_normalized_cross_correlation(
    y_true: tf.Tensor, y_pred: tf.Tensor, kernel_size: int = 9, **kwargs
) -> tf.Tensor:
    """
    moving a kernel/window on the y_true/y_pred
    then calculate the ncc in the window of y_true/y_pred
    average over all windows in the end

    :param y_true: shape = (batch, dim1, dim2, dim3, ch)
    :param y_pred: shape = (batch, dim1, dim2, dim3, ch)
    :param kernel_size: int
    :param kwargs: absorb additional parameters
    :return: shape = (batch,)
    """

    kernel_vol = kernel_size ** 3
    filters = tf.ones(
        shape=[kernel_size, kernel_size, kernel_size, 1, 1]
    )  # [dim1, dim2, dim3, d_in, d_out]
    strides = [1, 1, 1, 1, 1]
    padding = "SAME"

    # t = y_true, p = y_pred
    t2 = y_true * y_true
    p2 = y_pred * y_pred
    tp = y_true * y_pred

    t_sum = tf.nn.conv3d(y_true, filters=filters, strides=strides, padding=padding)
    p_sum = tf.nn.conv3d(y_pred, filters=filters, strides=strides, padding=padding)
    t2_sum = tf.nn.conv3d(t2, filters=filters, strides=strides, padding=padding)
    p2_sum = tf.nn.conv3d(p2, filters=filters, strides=strides, padding=padding)
    tp_sum = tf.nn.conv3d(tp, filters=filters, strides=strides, padding=padding)

    t_avg = t_sum / kernel_vol
    p_avg = p_sum / kernel_vol

    cross = tp_sum - p_avg * t_sum
    t_var = t2_sum - t_avg * t_sum
    p_var = p2_sum - p_avg * p_sum

    ncc = (cross * cross + EPS) / (t_var * p_var + EPS)
    return tf.reduce_mean(ncc, axis=[1, 2, 3, 4])


def ssd(y_true: tf.Tensor, y_pred: tf.Tensor) -> tf.Tensor:
    """
    sum of squared distance between y_true and y_pred

    :param y_true: shape = (batch, dim1, dim2, dim3, ch)
    :param y_pred: shape = (batch, dim1, dim2, dim3, ch)
    :return: shape = (batch,)
    """
    return tf.reduce_mean(tf.square(y_true - y_pred), axis=[1, 2, 3, 4])


def global_mutual_information(y_true: tf.Tensor, y_pred: tf.Tensor) -> tf.Tensor:
    """
    differentiable global mutual information loss via Parzen windowing method.
    reference: https://dspace.mit.edu/handle/1721.1/123142, Section 3.1, equation 3.1-3.5

    :y_true: shape = (batch, dim1, dim2, dim3, ch)
    :y_pred: shape = (batch, dim1, dim2, dim3, ch)
    :return: shape = (batch,)
    """
    bin_centers = tf.linspace(0.0, 1.1, 23)
    sigma_ratio = 0.5
    eps = 1.19209e-08

    sigma = (
        tf.reduce_mean(bin_centers[1:] - bin_centers[:-1]) * sigma_ratio
    )  # sigma in the Gaussian function (weighting function W)
    preterm = 1 / (2 * tf.math.square(sigma))

    batch, w, h, z, c = y_true.shape
    y_true = tf.reshape(y_true, [batch, w * h * z, 1])  # shape = (batch, nb_voxels, 1)
    y_pred = tf.reshape(y_pred, [batch, w * h * z, 1])  # shape = (batch, nb_voxels, 1)
    nb_voxels = y_true.shape[1] * 1.0  # number of voxels

    vbc = bin_centers[None, None, ...]  # shape = (batch, nb_voxels, num_bins)

    # each voxel contributes continuously to a range of histogram bin
    I_a = tf.math.exp(
        -preterm * tf.math.square(y_true - vbc)
    )  # shape = (batch, nb_voxels, num_bins)
    I_a /= tf.reduce_sum(I_a, -1, keepdims=True)  # shape = (batch, nb_voxels, num_bins)
    pa = tf.reduce_mean(I_a, axis=1, keepdims=True)  # shape = (batch, 1, num_bins)
    I_a_permute = tf.transpose(I_a, (0, 2, 1))  # shape = (batch, num_bins, nb_voxels)

    I_b = tf.math.exp(
        -preterm * tf.math.square(y_pred - vbc)
    )  # shape = (batch, nb_voxels, num_bins)
    I_b /= tf.reduce_sum(I_b, -1, keepdims=True)  # shape = (batch, nb_voxels, num_bins)
    pb = tf.reduce_mean(I_b, axis=1, keepdims=True)  # shape = (batch, 1, num_bins)

    pa = tf.transpose(pa, (0, 2, 1))  # shape = (batch, num_bins, 1)
    papb = tf.matmul(pa, pb) + eps  # shape = (batch, num_bins, num_bins)
    pab = tf.matmul(I_a_permute, I_b)  # shape = (batch, num_bins, num_bins)
    pab /= nb_voxels

    # MI: sum(P_ab * log(P_ab/P_aP_b + eps))
    return tf.reduce_sum(pab * tf.math.log(pab / papb + eps), axis=[1, 2])
