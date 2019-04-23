import tensorflow as tf
import collections


BatchedInput = collections.namedtuple('BatchedInput', ['initializer', 'source', 'target_input',
                                                       'target_output', 'source_sequence_length',
                                                       'target_sequence_length'])


def get_iterator(src_dataset, tgt_dataset, src_vocab_table, tgt_vocab_table,  #得到遍历器
                 batch_size, sos, eos, reshuffle_each_iteration=True,
                 src_max_len=None, tgt_max_len=None):
    src_eos_id = tf.cast(src_vocab_table.lookup(tf.constant(eos)), tf.int32)#找到结尾标记所对应的id
    tgt_sos_id = tf.cast(tgt_vocab_table.lookup(tf.constant(sos)), tf.int32)
    tgt_eos_id = tf.cast(tgt_vocab_table.lookup(tf.constant(eos)), tf.int32)
    output_buffer_size = batch_size * 1000

    src_tgt_dataset = tf.data.Dataset.zip((src_dataset, tgt_dataset))
    src_tgt_dataset.skip(0)
    src_tgt_dataset = src_tgt_dataset.shuffle(output_buffer_size, reshuffle_each_iteration=reshuffle_each_iteration)#打乱原有顺序
    #把每行字符串都分开，prefetch可以让数据处理和数据计算同时运行
    src_tgt_dataset = src_tgt_dataset.map(lambda src, tgt: (tf.string_split([src]).values,
                                                            tf.string_split([tgt]).values),
                                          num_parallel_calls=4).prefetch(output_buffer_size) 

    src_tgt_dataset = src_tgt_dataset.filter(lambda src, tgt: tf.logical_and(tf.size(src) > 0,
                                                                             tf.size(tgt) > 0))#删掉每行为空的数据
    if src_max_len:
        src_tgt_dataset = src_tgt_dataset.map(lambda src, tgt: (src[: src_max_len], tgt),
                                              num_parallel_calls=4).prefetch(output_buffer_size)#如果src有较长长度，就取src的最大限制长度
    if tgt_max_len:
        src_tgt_dataset = src_tgt_dataset.map(lambda src, tgt: (src, tgt[: tgt_max_len]),
                                              num_parallel_calls=4).prefetch(output_buffer_size)
    src_tgt_dataset = src_tgt_dataset.map(lambda src, tgt: (tf.cast(src_vocab_table.lookup(src), tf.int32),
                                                            tf.cast(tgt_vocab_table.lookup(tgt), tf.int32)),#将src和tgt换成数字索引
                                          num_parallel_calls=4).prefetch(output_buffer_size)

    src_tgt_dataset = src_tgt_dataset.map(lambda src, tgt: (src,
                                                            tf.concat(([tgt_sos_id], tgt), 0),#在各个句子的索引序列前后加上句子开始和结束索引
                                                            tf.concat((tgt, [tgt_eos_id]), 0)),
                                          num_parallel_calls=4).prefetch(output_buffer_size)
    src_tgt_dataset = src_tgt_dataset.map(lambda src, tgt_in, tgt_out: (src, tgt_in, tgt_out,
                                                                        tf.size(src), tf.size(tgt_in)),#加入原句子和输入翻译句子的大小
                                          num_parallel_calls=4).prefetch(output_buffer_size)

    def key_func(unused_1, unused_2, unused_3, src_len, tgt_len):
        if src_max_len:
            bucket_width = (src_max_len + 5 - 1) // 5 #桶的宽度
        else:
            bucket_width = 10     #桶的宽度为10
        bucked_id = tf.maximum(src_len // bucket_width, tgt_len // bucket_width) #看看可以分在哪个桶里面
        return tf.to_int64(tf.minimum(5, bucked_id)) #返回同所在的索引

    def reduce_func(unused_key, windowed_data):
        return windowed_data.padded_batch(
            batch_size,
            padded_shapes=(tf.TensorShape([None]), tf.TensorShape([None]),
                           tf.TensorShape([None]), tf.TensorShape([]), tf.TensorShape([])),
            padding_values=(src_eos_id, tgt_eos_id, tgt_eos_id, 0, 0))#把每个桶的句子填补齐
      
    batched_dataset = src_tgt_dataset.apply(tf.contrib.data.group_by_window(
        key_func=key_func, reduce_func=reduce_func, window_size=batch_size))#对数据集中的每一行进行分桶打包

    batched_iterator = batched_dataset.make_initializable_iterator()
    src_ids, tgt_input_ids, tgt_output_ids, src_seq_len, tgt_seq_len = batched_iterator.get_next() #可以做遍历器了

    batched_input = BatchedInput(initializer=batched_iterator.initializer,
                                 source=src_ids, target_input=tgt_input_ids,
                                 target_output=tgt_output_ids,
                                 source_sequence_length=src_seq_len,
                                 target_sequence_length=tgt_seq_len)
    return batched_input


def get_infer_iterator(src_dataset, src_vocab_table, batch_size, eos, src_max_len=None):
    src_eos_id = tf.cast(src_vocab_table.lookup(tf.constant(eos)), tf.int32)#把eos换成数字索引
    src_dataset = src_dataset.map(lambda src: tf.string_split([src]).values)#把src以空格分开形列表

    if src_max_len:
        src_dataset = src_dataset.map(lambda src: src[: src_max_len])#取允许最大长度
    src_dataset = src_dataset.map(lambda src: tf.cast(src_vocab_table.lookup(src), tf.int32))#把src换成数字索引
    src_dataset = src_dataset.map(lambda src: (src, tf.size(src)))

    batched_dataset = src_dataset.padded_batch(batch_size,
                                               padded_shapes=([-1], []),
                                               padding_values=(src_eos_id, 0))#把每行填充成相同长度
    batched_iterator = batched_dataset.make_initializable_iterator()
    src_ids, src_seq_len = batched_iterator.get_next()

    batched_input = BatchedInput(initializer=batched_iterator.initializer,
                                 source=src_ids, target_input=None, target_output=None,
                                 source_sequence_length=src_seq_len,
                                 target_sequence_length=None)
    return batched_input
